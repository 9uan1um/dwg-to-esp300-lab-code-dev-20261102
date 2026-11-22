"""Ready integration tests with forbidden hardware opens and simulated serial replies."""
import json
import math
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import visualizer_server as app
from ready_position import ReadyPositionStore

ROOT = Path(__file__).resolve().parent
SAVED = dict(x=-19.125, y=6.25, z=10.9342)


class ReadyTests(unittest.TestCase):
    def setUp(self):
        guard = patch.object(app, 'open_esp300', side_effect=AssertionError('Hardware forbidden'))
        guard.start(); self.addCleanup(guard.stop)
        recorder = patch.object(app.app_audit, 'RECORDER', Mock())
        recorder.start(); self.addCleanup(recorder.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'ready.json'
        ReadyPositionStore(self.path).save(SAVED, 'test-fixture')
        self.limit_path = Path(self.tmp.name) / 'z-max-mm.json'
        self.limit_path.write_text('12.34525', encoding='utf-8')
        self.jog = app.JogController(self.path, self.limit_path)
        self.jog.connected = True
        self.jog.dry_run = True
        self.jog.raw_position = {n: v - 1 for n, v in SAVED.items()}
        self.jog.local_offset = dict(x=-26.625, y=13.75, z=71.00845)
        self.jog.position = {n: self.jog._local_of(n, v) for n, v in self.jog.raw_position.items()}
        self.jog.focus_trim_mm = 61
        self.jog.z_home_raw = 10.00845
        self.commands = []

    def start(self, axes, mode=None):
        return getattr(self.jog, 'move_to_saved_' + axes)(mode or ('mock' if self.jog.dry_run else 'live'))

    def finish(self):
        self.jog._run_thread.join(5)
        self.assertFalse(self.jog._run_thread.is_alive())
        return self.jog.run_status()

    def fake_live(self, stuck=False, fail=False, mutate=False, drift=False, start_moving=False):
        self.jog.dry_run = False
        self.jog.ser = Mock()
        self.device = dict(self.jog.raw_position)
        self.pa = threading.Event()
        axes = {v: k for k, v in app.JOG_AXES.items()}

        def write(cmd):
            self.commands.append(cmd)
            if cmd[1:3] == 'PA':
                if not stuck:
                    self.device[axes[int(cmd[0])]] = float(cmd[3:])
                self.pa.set()
                if mutate:
                    self.jog.local_offset['x'] += .1
                if drift:
                    self.device['z'] += .01

        def query(cmd):
            if cmd == 'TE?': return '0'
            if cmd.endswith('MO?'): return '1'
            if cmd.endswith('MD?'):
                return '0' if start_moving or (stuck and self.pa.is_set() and 'ST' not in self.commands) else '1'
            if cmd.endswith('TP'):
                if fail and self.pa.is_set() and 'ST' not in self.commands:
                    raise RuntimeError('Injected telemetry failure')
                return str(self.device[axes[int(cmd[0])]])
            raise AssertionError(cmd)

        self.jog._write, self.jog._query = write, query

    def test_initial_preset_and_two_coordinate_frames(self):
        status = self.jog.status()
        self.assertEqual(status['ready']['saved']['position'], SAVED)
        self.assertNotEqual(status['position'], status['rawPosition'])
        self.assertEqual(status['localOffset'], self.jog.local_offset)

    def test_selected_axes_only_and_no_reference_change(self):
        for axes in ('xy', 'z', 'xyz'):
            with self.subTest(axes=axes):
                self.jog.raw_position = {n: v - 1 for n, v in SAVED.items()}
                self.jog.position = {n: self.jog._local_of(n, v) for n, v in self.jog.raw_position.items()}
                before = dict(self.jog.raw_position)
                context = self.jog._run_context_locked()
                self.commands = []
                self.fake_live()
                self.start(axes)
                self.assertTrue(self.finish()['done'])
                moves = [c for c in self.commands if c[1:3] == 'PA']
                self.assertEqual(moves, [f'{app.JOG_AXES[n]}PA{SAVED[n]:.6f}' for n in axes])
                self.assertEqual({int(c[0]) for c in self.commands if c[1:3] == 'VA'},
                                 {app.JOG_AXES[n] for n in axes})
                self.assertEqual(self.jog.raw_position, {n: SAVED[n] if n in axes else before[n] for n in 'xyz'})
                self.assertEqual(context, self.jog._run_context_locked())
                self.assertEqual(self.jog.focus_trim_mm, 61)

    def test_local_home_change_preserves_saved_machine_position(self):
        initial = self.path.read_bytes()
        self.jog.set_local_home(100, 200, 300)
        self.assertEqual(self.path.read_bytes(), initial)
        self.fake_live()
        self.start('xyz')
        self.assertTrue(self.finish()['done'])
        self.assertEqual(self.jog.raw_position, SAVED)
        self.assertEqual([c for c in self.commands if c[1:3] == 'PA'],
                         [f'{app.JOG_AXES[n]}PA{SAVED[n]:.6f}' for n in 'xyz'])

    def test_dry_run_preserves_unselected_axis(self):
        before = dict(self.jog.raw_position)
        self.start('xy')
        self.assertTrue(self.finish()['done'])
        self.assertEqual(self.jog.raw_position['z'], before['z'])
        self.assertEqual(self.jog.raw_position['y'], SAVED['y'])

    def test_already_at_target_sends_no_motion(self):
        self.jog.raw_position = dict(SAVED)
        self.fake_live()
        self.start('xyz')
        self.assertTrue(self.finish()['done'])
        self.assertEqual(self.commands, [])

    def test_small_real_difference_is_not_skipped(self):
        self.jog.raw_position['z'] = SAVED['z'] - .0005
        self.fake_live()
        self.start('z')
        self.assertTrue(self.finish()['done'])
        self.assertIn(f'3PA{SAVED["z"]:.6f}', self.commands)

    def test_saved_z_outside_workspace_only_blocks_z_and_xyz(self):
        self.jog.save_ready_position({**SAVED, 'x': 120, 'z': 17.375})
        self.fake_live()
        self.start('xy')
        self.assertTrue(self.finish()['done'])
        self.commands.clear()
        for axes in ('z', 'xyz'):
            with self.assertRaisesRegex(ValueError, 'Machine Z'):
                self.start(axes)
        self.assertEqual(self.commands, [])

    def test_save_reload_and_failed_atomic_save_preserve_previous_file(self):
        position = dict(x=-1, y=2, z=3)
        self.jog.save_ready_position(position)
        self.assertEqual(ReadyPositionStore(self.path).value['position'], position)
        content = self.path.read_bytes()
        with patch('ready_position.os.replace', side_effect=OSError('disk failed')):
            with self.assertRaises(OSError): self.jog.save_ready_position(SAVED)
        self.assertEqual(self.path.read_bytes(), content)
        self.assertEqual(self.jog.ready_position.value['position'], position)
        self.assertFalse(list(self.path.parent.glob('*.tmp')))

    def test_invalid_saved_values_and_corrupt_file_do_not_move(self):
        content = self.path.read_bytes()
        for invalid in (None, {}, {'x': 1, 'y': 2}, dict(x=True, y=2, z=3),
                        dict(x=math.nan, y=2, z=3), dict(x=1, y=2, z=math.inf)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                self.jog.save_ready_position(invalid)
        self.assertEqual(self.path.read_bytes(), content)
        self.path.write_text('{broken', encoding='utf-8')
        self.jog.ready_position = ReadyPositionStore(self.path)
        with self.assertRaises(RuntimeError): self.start('xyz')
        self.assertIsNone(self.jog._run_thread)

    def test_capture_reads_current_controller_not_cached_display(self):
        with self.assertRaises(RuntimeError): self.jog.capture_ready_position('mock')
        self.fake_live()
        self.device = dict(x=-40, y=11, z=18)
        self.jog.capture_ready_position('live')
        self.assertEqual(ReadyPositionStore(self.path).value['position'], self.device)
        self.assertEqual(self.commands, [])

    def test_modes_activity_and_stationary_guard(self):
        with self.assertRaises(RuntimeError): self.start('xyz', 'live')
        self.jog.connected = False
        with self.assertRaises(RuntimeError): self.start('z')
        self.jog.connected = True
        for state in (self.jog._run_state, self.jog._sensor_home_state):
            state['running'] = True
            with self.assertRaises(RuntimeError): self.start('xy')
            with self.assertRaises(RuntimeError): self.jog.save_ready_position(SAVED)
            state['running'] = False
        self.jog._manual_target_raw = dict(SAVED)
        with self.assertRaises(RuntimeError): self.start('xy')
        self.jog._manual_target_raw = None
        self.fake_live(start_moving=True)
        with self.assertRaises(RuntimeError): self.start('xyz')
        self.assertEqual(self.commands, [])

    def test_stop_has_no_return_or_unselected_motion(self):
        self.fake_live(stuck=True)
        self.start('xy')
        self.assertTrue(self.pa.wait(1))
        with self.assertRaises(RuntimeError): self.start('z')
        self.jog.run_stop()
        result = self.finish()
        self.assertFalse(result['done'])
        self.assertTrue(result['stopConfirmed'])
        self.assertIn('ST', self.commands)
        self.assertFalse(any(c.startswith('3PA') for c in self.commands))
        self.assertLessEqual(len([c for c in self.commands if c[1:3] == 'PA']), 2)

    def test_telemetry_fault_and_context_change_stop(self):
        for failure in ('fail', 'mutate', 'drift'):
            with self.subTest(failure=failure):
                self.commands = []
                self.jog.raw_position = {n: v - 1 for n, v in SAVED.items()}
                self.fake_live(**{failure: True})
                self.start('xy')
                result = self.finish()
                self.assertFalse(result['done'])
                self.assertTrue(result['stopConfirmed'])
                self.assertIn('ST', self.commands)

    def test_raw_ready_segments_cannot_be_injected_through_generic_plan(self):
        with self.assertRaises(ValueError): self.jog.run_plan([{'readyMove': True}])

    def test_http_routes_with_isolated_mock_controller(self):
        class QuietHandler(app.VisualizerHandler):
            def log_message(self, *args): pass
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), QuietHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        base = f'http://127.0.0.1:{server.server_port}'
        def post(path, body):
            req = Request(base + path, json.dumps(body).encode(), {'Content-Type': 'application/json'})
            with urlopen(req, timeout=3) as response: return json.load(response)
        with patch.object(app, 'JOG', self.jog):
            thread.start()
            try:
                with urlopen(base + '/api/jog/status') as response:
                    self.assertEqual(json.load(response)['ready']['saved']['position'], SAVED)
                with urlopen(base + '/') as response:
                    html = response.read().decode()
                    self.assertIn('<legend>Ready</legend>', html)
                    for key in ('readyXY', 'readyZ', 'readyXYZ'):
                        self.assertEqual(html.count(f'id="{key}"'), 1)
                self.assertIn('id="jogZMax"', html)
                self.assertEqual(post('/api/jog/z-limit', {'zMaxMm': 11})['zMaxMm'], 11)
                with self.assertRaises(HTTPError):
                    post('/api/jog/z-limit', {'zMaxMm': None})
                self.assertEqual(app.JogController(self.path, self.limit_path).z_max_mm, 11)
                result = post('/api/jog/ready/save', {'position': SAVED})
                self.assertEqual(result['ready']['saved']['position'], SAVED)
                result = post('/api/jog/ready/move', {'axes': 'xyz', 'mode': 'mock'})
                self.assertEqual(result['readyAxes'], 'xyz')
                self.assertTrue(self.finish()['done'])
                with self.assertRaises(HTTPError): post('/api/jog/ready/move', {'axes': 'x', 'mode': 'mock'})
                with self.assertRaises(HTTPError): post('/api/jog/ready/capture', {'mode': 'mock'})
            finally:
                server.shutdown(); server.server_close(); thread.join(2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
