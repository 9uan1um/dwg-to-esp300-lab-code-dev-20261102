"""Hardware-free circle geometry, worker, guard and dispatch regression checks."""
import math
import threading
import unittest
import json
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

import circle_test
import integrated_substrate as integration
import test_point_test as fixtures
import visualizer_server as app


class CircleTests(unittest.TestCase):
    setUp = fixtures.PointTests.setUp
    finish = fixtures.PointTests.finish
    live_fake = fixtures.PointTests.live_fake

    def start(self, **settings):
        return circle_test.start_circle(self.jog, dict(mode='mock' if self.jog.dry_run else 'live', **settings))

    def test_geometry_repeats_same_circle_and_retracts_before_centering(self):
        start = [12.5, 12.5, 1.25]
        segments = circle_test.compile_circle(start, 2, .5, 3, .1, self.jog)
        self.assertEqual(len(segments), 3 * 180 + 4)
        self.assertEqual([s['to3'] for s in segments[:2]], [[14.5, 12.5, 1.25], [14.5, 12.5, 1.35]])
        traces = [s for s in segments if s['kind'] == 'circle_trace']
        for s in traces:
            self.assertAlmostEqual(math.dist(s['to3'][:2], start[:2]), 2)
            self.assertEqual(s['to3'][2], 1.35)
            self.assertEqual(s['speedMmS'], .5)
        for repeat in range(1, 4):
            turn = [s for s in traces if s['pathIndex'] == repeat]
            self.assertEqual(len(turn), 180)
            self.assertEqual(turn[-1]['to3'], turn[0]['from3'])
            self.assertGreater(turn[0]['to3'][1], start[1])
        self.assertEqual([s['to3'] for s in segments[-2:]], [[14.5, 12.5, 1.25], start])
        self.assertEqual([s['speedMmS'] for s in segments if s['zOnly']], [1., 1.])
        for previous, following in zip(segments, segments[1:]):
            self.assertEqual(previous['to3'], following['from3'])

    def test_zero_offset_has_no_z_move(self):
        segments = circle_test.compile_circle([12.5, 12.5, 1.25], 1, 1, 2, 0, self.jog)
        self.assertEqual(len(segments), 362)
        self.assertFalse(any(s['zOnly'] for s in segments))
        self.assertEqual(segments[-1]['to3'], [12.5, 12.5, 1.25])

    def test_invalid_parameters_and_limits_never_start(self):
        cases = [dict(radius_mm=v) for v in (0, -1, .0001, True, '1', None, float('inf'), float('nan'))]
        cases += [dict(repeat_count=v) for v in (0, -1, 1.5, True, '2', None, 1001)]
        cases += [dict(focus_offset_mm=v) for v in (-1, .0001, True, '1', None, float('inf'), 20)]
        cases += [dict(xy_speed=v) for v in (0, .001, 11, True, None, float('nan'))]
        for settings in cases:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.start(**settings)
        self.assertIsNone(self.jog._run_thread)

    def test_large_circle_has_no_xy_limit(self):
        with patch.object(app.time, 'sleep', return_value=None):
            self.start(radius_mm=100)
            self.assertTrue(self.finish()['done'])

    def test_mock_complete_at_start_with_all_turns(self):
        with patch.object(app.time, 'sleep', return_value=None):
            self.start(radius_mm=.3, repeat_count=3, focus_offset_mm=.2)
            self.assertTrue(self.finish()['done'])
        self.assertEqual(self.jog.run_status()['index'], 544)
        self.assertEqual(self.jog.position, dict(x=12.5, y=12.5, z=1.25))

    def test_live_fake_measured_center_offsets_and_z_once(self):
        self.jog.local_offset.update(x=4, y=2, z=7)
        self.jog.raw_position = {k: self.jog._raw_of(k, v) for k, v in self.jog.position.items()}
        self.live_fake()
        self.jog.position['x'] = 0  # Stale display cache must not set the center.
        self.jog._alignment_required = True
        with patch.object(app.time, 'sleep', return_value=None):
            self.start(radius_mm=.3, repeat_count=2, focus_offset_mm=.2, xy_speed=.5)
            result = self.finish()
        self.assertTrue(result['done'], result)
        self.assertEqual(self.jog._run_segments[0]['from3'], [12.5, 12.5, 1.25])
        self.assertEqual([c for c in self.commands if c.startswith('3PA')], ['3PA8.450000', '3PA8.250000'])
        self.assertEqual(self.commands[-1], '1PA16.500000')
        self.assertEqual(self.jog.position, dict(x=12.5, y=12.5, z=1.25))
        self.assertTrue(self.jog._alignment_required)
        with self.assertRaisesRegex(RuntimeError, 'Set local home'):
            self.jog.run_plan([dict(to3=[12.5, 12.5, 1.25], duration=1)])

    def test_stop_during_trace_and_resume_keeps_original_circle(self):
        self.live_fake(moving=True)
        # Signal the simulated moving state only after the first arc command.
        write = self.jog._write
        trace_started = threading.Event()
        def delayed_signal(command):
            write(command)
            if command[1:3] == 'PA' and len([c for c in self.commands if c[1:3] == 'PA']) < 3:
                self.pa.clear()
            elif command[1:3] == 'PA':
                trace_started.set()
        self.jog._write = delayed_signal
        started = self.start(radius_mm=.3, repeat_count=2, focus_offset_mm=.1)
        self.assertTrue(trace_started.wait(2))
        self.jog.run_stop()
        result = self.finish()
        self.assertTrue(result['stopConfirmed'])
        self.assertEqual(result['index'], 2)
        self.assertFalse(result['done'])
        self.assertNotIn('3PA1.250000', self.commands)  # No auto-return on stop.
        original = self.jog._run_segments
        with patch.object(app.time, 'sleep', return_value=None):
            self.jog.run_resume(started['jobId'])
            self.assertTrue(self.finish()['done'])
        self.assertEqual(self.jog._run_segments, original)
        self.assertEqual(self.jog.position, dict(x=12.5, y=12.5, z=1.25))

    def test_fault_and_context_change_stop_before_further_motion(self):
        for fault in ('fault', 'mutate'):
            with self.subTest(fault=fault):
                self.live_fake(**{fault: True})
                self.start(focus_offset_mm=.1)
                result = self.finish()
                self.assertTrue(result['stopConfirmed'])
                self.assertFalse(result['done'])
                self.assertEqual(len([c for c in self.commands if c[1:3] == 'PA']), 1)

    def test_mode_connection_and_activity_guards(self):
        with self.assertRaises(RuntimeError):
            circle_test.start_circle(self.jog, dict(mode='live'))
        self.jog.connected = False
        with self.assertRaises(RuntimeError):
            self.start()
        self.jog.connected = True
        for state in (self.jog._sensor_home_state, self.jog._run_state):
            state['running'] = True
            with self.assertRaises(RuntimeError):
                self.start()
            state['running'] = False
        with self.assertRaises(ValueError):
            self.jog.run_plan([], circle_settings={}, line_settings={})
        self.assertIsNone(self.jog._run_thread)

    def test_dispatch_status_progress_without_substrate_registration(self):
        namespace = dict(JOG=self.jog, DEPTH_CONTEXT=app.DepthContext(), JOG_AXES=app.JOG_AXES,
                         ESP300_AXIS_SIGNS=app.ESP300_AXIS_SIGNS)
        handler = Mock(command='POST')
        handler.read_json.return_value = dict(mode='mock', radius_mm=.3, repeat_count=2, focus_offset_mm=.1)
        with patch.object(integration, 'engine', None), patch.object(integration, 'last_context', None):
            with patch.object(app.time, 'sleep', return_value=None):
                integration.dispatch(handler, namespace, 'circle-run')
                handler.send_error_json.assert_not_called()
                self.assertTrue(self.finish()['done'])
            handler.command = 'GET'
            integration.dispatch(handler, namespace, 'status')
            result = handler.send_json.call_args.args[0]
            self.assertEqual(result['test_type'], 'circle')
            self.assertEqual(result['state']['completed'], 364)
            self.assertEqual(result['state']['total'], 364)
            self.assertIsNone(result['upper_right'])
            with patch.object(self.jog, 'run_status', return_value=dict(running=True, index=2)):
                integration.dispatch(handler, namespace, 'status')
            self.assertEqual(handler.send_json.call_args.args[0]['state']['phase'], 'circle_trace')

    def test_http_ui_and_circle_run_on_isolated_mock_server(self):
        app.app_audit.RECORDER.health.return_value = {'simulated': True}
        server = app.ThreadingHTTPServer(('127.0.0.1', 0), app.VisualizerHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        url = f'http://127.0.0.1:{server.server_port}'
        with patch.object(app, 'JOG', self.jog), patch.object(app, 'DEPTH_CONTEXT', app.DepthContext()), \
                patch.object(integration, 'engine', None), patch.object(integration, 'last_context', None):
            thread.start()
            try:
                with urlopen(url + '/') as response:
                    html = response.read().decode()
                for element in ('circleRadius', 'circleSpeed', 'circleRepeatCount', 'circleFocusOffset'):
                    self.assertEqual(html.count(f'id="{element}"'), 1)
                with urlopen(url + '/substrate-dialog.js?v=circle-20261116') as response:
                    self.assertIn("action='circle-run'", response.read().decode())
                body = dict(mode='mock', radius_mm=.3, xy_speed=.5, repeat_count=2, focus_offset_mm=.1)
                request = Request(url + '/api/substrate/circle-run', json.dumps(body).encode(),
                                  {'Content-Type': 'application/json'})
                with patch.object(app.time, 'sleep', return_value=None):
                    with urlopen(request) as response:
                        result = json.load(response)
                    self.assertEqual(result['total'], 364)
                    self.assertTrue(self.finish()['done'])
                with urlopen(url + '/api/substrate/status') as response:
                    result = json.load(response)
                self.assertEqual(result['test_type'], 'circle')
                self.assertEqual(result['state']['status'], 'completed')
                self.assertEqual(result['position'], [12.5, 12.5, 1.25])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
