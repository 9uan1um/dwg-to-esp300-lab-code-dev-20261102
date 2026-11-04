"""Hardware-free point recipe, dispatch and real worker command tests."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import threading
import unittest
from unittest.mock import Mock, patch

import integrated_substrate as integration
import point_test
import visualizer_server as app


class PointTests(unittest.TestCase):
    def setUp(self):
        self.guard = patch.object(app, 'open_esp300', side_effect=AssertionError('Hardware forbidden'))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        recorder = patch.object(app.app_audit, 'RECORDER', Mock())
        recorder.start()
        self.addCleanup(recorder.stop)
        self.jog = app.JogController()
        self.jog.connected = True
        self.jog.dry_run = True
        self.jog.position = dict(x=12.5, y=12.5, z=1.25)
        self.jog.raw_position = {k: self.jog._raw_of(k, v) for k, v in self.jog.position.items()}

    def finish(self):
        self.jog._run_thread.join(3)
        self.assertFalse(self.jog._run_thread.is_alive())
        return self.jog.run_status()

    def live_fake(self, moving=False, fault=False, mutate=False):
        self.jog.dry_run = False
        self.jog.ser = Mock()
        self.commands = []
        self.pa = threading.Event()
        raw = dict(self.jog.raw_position)
        axes = {axis: name for name, axis in app.JOG_AXES.items()}

        def write(command):
            self.commands.append(command)
            if command[1:3] == 'PA':
                raw[axes[int(command[0])]] = float(command[3:])
                self.pa.set()
                if mutate:
                    self.jog.z_range += 1
        def query(command):
            if command == 'TE?':
                return '0'
            if command.endswith('MO?'):
                return '1'
            if command.endswith('MD?'):
                return '0' if moving and self.pa.is_set() and 'ST' not in self.commands else '1'
            if command.endswith('TP'):
                if fault and self.pa.is_set() and 'ST' not in self.commands:
                    raise RuntimeError('Injected read fault')
                return str(raw[axes[int(command[0])]])
            raise AssertionError(command)
        self.jog._write = write
        self.jog._query = query

    def test_default_two_z_segments_from_nonzero_start(self):
        segments = point_test.compile_point([12.5, 12.5, 1.25], 3, .01, self.jog)
        self.assertEqual([s['to3'] for s in segments], [[12.5, 12.5, 4.25], [12.5, 12.5, 1.25]])
        self.assertEqual([s['speedMmS'] for s in segments], [.01, 1.0])
        self.assertEqual([s['duration'] for s in segments], [300.0, 3.0])
        self.assertTrue(all(s['zOnly'] for s in segments))

    def test_dry_run_and_custom_settings(self):
        point_test.start_point(self.jog, dict(mode='mock', depth_mm=2.5, ingress_speed=.2, return_speed=9))
        self.assertTrue(self.finish()['done'])
        self.assertEqual(self.jog.position, dict(x=12.5, y=12.5, z=1.25))
        self.assertEqual([s['speedMmS'] for s in self.jog._run_segments], [.2, 1.0])

    def test_live_worker_only_issues_z_ingress_and_fixed_return(self):
        self.live_fake()
        point_test.start_point(self.jog, dict(mode='live'))
        self.assertTrue(self.finish()['done'])
        z = app.JOG_AXES['z']
        self.assertEqual(self.commands, [f'{z}VA0.010000', f'{z}PA4.250000', f'{z}VA1.000000', f'{z}PA1.250000'])

    def test_point_needs_no_local_home_or_upper_right_after_sensor_home(self):
        self.live_fake()
        self.jog._alignment_required = True
        self.assertIsNone(getattr(self.jog, '_substrate_upper_right', None))
        point_test.start_point(self.jog, dict(mode='live'))
        self.assertTrue(self.finish()['done'])
        self.assertTrue(self.jog._alignment_required)
        # Drawing paths still require their own alignment.
        with self.assertRaisesRegex(RuntimeError, 'Set local home'):
            self.jog.run_plan([dict(to3=[12.5, 12.5, 1.25], duration=1)])

    def test_invalid_inputs_and_limits_never_start(self):
        for depth, speed in [(0, .01), (-1, .01), (True, .01), (float('nan'), .01),
                             (3, 0), (3, .001), (3, 11), (3, float('inf')), (3, '0.01'), (20, .01)]:
            with self.subTest(depth=depth, speed=speed), self.assertRaises(ValueError):
                point_test.start_point(self.jog, dict(mode='mock', depth_mm=depth, ingress_speed=speed))
        self.assertIsNone(self.jog._run_thread)
        self.jog.position['x'] = 100
        self.jog.raw_position['x'] = self.jog._raw_of('x', 100)
        with self.assertRaisesRegex(ValueError, 'XY limit'):
            point_test.start_point(self.jog, dict(mode='mock'))

    def test_connection_mode_and_busy_guards(self):
        with self.assertRaisesRegex(RuntimeError, '모드'):
            point_test.start_point(self.jog, dict(mode='live'))
        self.jog.connected = False
        with self.assertRaisesRegex(RuntimeError, '연결'):
            point_test.start_point(self.jog, dict(mode='mock'))
        self.jog.connected = True
        self.jog._sensor_home_state['running'] = True
        with self.assertRaises(RuntimeError):
            point_test.start_point(self.jog, dict(mode='mock'))
        self.jog._sensor_home_state['running'] = False
        self.jog._run_state['running'] = True
        with self.assertRaises(RuntimeError):
            point_test.start_point(self.jog, dict(mode='mock'))

    def test_stop_during_ingress_does_not_return(self):
        self.live_fake(moving=True)
        point_test.start_point(self.jog, dict(mode='live'))
        self.assertTrue(self.pa.wait(1))
        self.jog.run_stop()
        result = self.finish()
        self.assertFalse(result['done'])
        self.assertTrue(result['stopConfirmed'])
        self.assertEqual(len([c for c in self.commands if c[1:3] == 'PA']), 1)
        self.assertIn('ST', self.commands)

    def test_fault_during_ingress_does_not_return(self):
        self.live_fake(fault=True)
        point_test.start_point(self.jog, dict(mode='live'))
        result = self.finish()
        self.assertIn('Injected read fault', result['error'])
        self.assertTrue(result['stopConfirmed'])
        self.assertEqual(len([c for c in self.commands if c[1:3] == 'PA']), 1)

    def test_resume_keeps_original_start_and_fixed_return(self):
        self.live_fake(moving=True)
        started = point_test.start_point(self.jog, dict(mode='live'))
        self.assertTrue(self.pa.wait(1))
        self.jog.run_stop()
        self.assertTrue(self.finish()['resumable'])
        self.jog.run_resume(started['jobId'])
        self.assertTrue(self.finish()['done'])
        self.assertEqual(self.commands[-2:], ['3VA1.000000', '3PA1.250000'])

    def test_local_coordinate_offset_preserves_physical_start(self):
        self.jog.local_offset['z'] = 7.0
        self.jog.raw_position['z'] = 8.25
        self.live_fake()
        point_test.start_point(self.jog, dict(mode='live'))
        self.assertTrue(self.finish()['done'])
        self.assertEqual(self.commands, ['3VA0.010000', '3PA11.250000', '3VA1.000000', '3PA8.250000'])

    def test_context_change_during_ingress_stops_before_return(self):
        self.live_fake(mutate=True)
        point_test.start_point(self.jog, dict(mode='live'))
        self.assertIn('configuration changed', self.finish()['error'])
        self.assertEqual(len([c for c in self.commands if c[1:3] == 'PA']), 1)

    def test_dispatch_and_point_status_without_substrate_reference(self):
        namespace = dict(JOG=self.jog, DEPTH_CONTEXT=app.DepthContext(), JOG_AXES=app.JOG_AXES,
                         ESP300_AXIS_SIGNS=app.ESP300_AXIS_SIGNS, FOCUS=Mock())
        namespace['FOCUS'].status.return_value = {}
        handler = Mock(command='POST')
        handler.read_json.return_value = dict(mode='mock')
        with patch.object(integration, 'engine', None), patch.object(integration, 'last_context', None):
            integration.dispatch(handler, namespace, 'point-run')
            handler.send_error_json.assert_not_called()
            self.assertTrue(self.finish()['done'])
            handler.command = 'GET'
            integration.dispatch(handler, namespace, 'status')
            result = handler.send_json.call_args.args[0]
            self.assertEqual(result['test_type'], 'point')
            self.assertEqual(result['state']['total'], 2)
            self.assertEqual(result['state']['completed'], 2)
            self.assertIsNone(result['upper_right'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
