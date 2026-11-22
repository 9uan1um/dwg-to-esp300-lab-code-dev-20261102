"""Hardware-free recipe, dispatch, stop/resume and real-worker command checks."""
import unittest
from unittest.mock import Mock, patch

import integrated_substrate as integration
import line_test
import test_point_test as fixtures
import visualizer_server as app


class LineTests(unittest.TestCase):
    setUp = fixtures.PointTests.setUp
    finish = fixtures.PointTests.finish
    live_fake = fixtures.PointTests.live_fake

    def start(self, **settings):
        return line_test.start_line(self.jog, dict(mode='mock' if self.jog.dry_run else 'live', **settings))

    def test_one_way_repeats_retract_at_endpoint_and_reset_y_at_start_z(self):
        segments = line_test.compile_line([12.5, 12.5, 1.25], 2, 3, .125, .5, .5, False)
        self.assertEqual([s['to3'] for s in segments], [
            [12.5, 12.5, 1.75], [12.5, 10.5, 1.75], [12.5, 10.5, 1.25], [12.5, 12.5, 1.25],
            [12.5, 12.5, 1.875], [12.5, 10.5, 1.875], [12.5, 10.5, 1.25], [12.5, 12.5, 1.25],
            [12.5, 12.5, 2.0], [12.5, 10.5, 2.0], [12.5, 10.5, 1.25], [12.5, 12.5, 1.25]])
        self.assertAlmostEqual(sum(s['duration'] for s in segments), 27.75)
        self.assertTrue(all(s['yOnly'] != s['zOnly'] for s in segments))

    def test_mock_completes_at_original_xyz(self):
        self.start(length_mm=2, repeat_count=3, z_step_mm=.1, xy_speed=.5, round_trip=True)
        result = self.finish()
        self.assertTrue(result['done'])
        self.assertEqual(result['index'], 9)
        self.assertEqual(self.jog.position, dict(x=12.5, y=12.5, z=1.25))

    def test_live_commands_have_only_y_and_z_and_preserve_local_offsets(self):
        self.jog.local_offset.update(x=9, y=4, z=7)
        self.jog.raw_position = {k: self.jog._raw_of(k, v) for k, v in self.jog.position.items()}
        self.live_fake()
        self.start(length_mm=-2, depth_mm=.5, xy_speed=.5, round_trip=True)
        self.assertTrue(self.finish()['done'])
        # Existing Y mapping is negative: raw Y = -local Y + offset.
        self.assertEqual(self.commands, [
            '3VA1.000000', '3PA8.750000', '2VA0.500000', '2PA-10.500000',
            '2VA0.500000', '2PA-8.500000', '3VA1.000000', '3PA8.250000'])

    def test_signed_one_way_returns_z_at_endpoint_before_returning_y(self):
        self.live_fake()
        self.start(length_mm=-2, depth_mm=.5)
        self.assertTrue(self.finish()['done'])
        self.assertEqual([c for c in self.commands if c[1:3] == 'PA'],
                         ['3PA1.750000', '2PA-14.500000', '3PA1.250000', '2PA-12.500000'])

    def test_one_repeat_or_zero_step_has_no_z_motion(self):
        for repeats, step in [(1, 100), (3, 0)]:
            with self.subTest(repeats=repeats, step=step):
                self.live_fake()
                self.start(repeat_count=repeats, z_step_mm=step)
                self.assertTrue(self.finish()['done'])
                self.assertEqual(len(self.commands), repeats * 4)
                self.assertTrue(all(c.startswith('2') for c in self.commands))

    def test_bad_inputs_and_limits_rejected_before_motion(self):
        cases = [dict(length_mm=v) for v in (0, -.0001, .0001, True, '1', None, float('inf'), float('nan'))]
        cases += [dict(depth_mm=v) for v in (-.1, .0001, True, '1', None, float('nan'), 100)]
        cases += [dict(round_trip=v) for v in (1, 'false', None)]
        cases += [dict(repeat_count=v) for v in (0, -1, 1.5, True, '2', None, 10001)]
        cases += [dict(z_step_mm=v) for v in (-1, .0001, True, '1', None, float('inf'))]
        cases += [dict(xy_speed=v) for v in (0, .001, 11, True, None, float('nan'))]
        cases += [dict(repeat_count=3, z_step_mm=10)]
        for settings in cases:
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.start(**settings)
        self.assertIsNone(self.jog._run_thread)

    def test_y_sweeps_outside_previous_xy_circle(self):
        self.start(length_mm=100)
        self.assertTrue(self.finish()['done'])

    def test_stop_prevents_further_sweeps_and_return_then_resume_uses_original_start(self):
        self.live_fake(moving=True)
        started = self.start(repeat_count=2, z_step_mm=.1)
        self.assertTrue(self.pa.wait(1))
        self.jog.run_stop()
        result = self.finish()
        self.assertTrue(result['stopConfirmed'])
        self.assertFalse(result['done'])
        self.assertEqual([c for c in self.commands if c[1:3] == 'PA'], ['2PA-11.500000'])
        self.jog.run_resume(started['jobId'])
        self.assertTrue(self.finish()['done'])
        self.assertEqual(self.commands[-4:], ['3VA1.000000', '3PA1.250000', '2VA1.000000', '2PA-12.500000'])
        self.assertEqual(self.jog.position, dict(x=12.5, y=12.5, z=1.25))

    def test_read_fault_stops_without_return(self):
        self.live_fake(fault=True)
        self.start(repeat_count=2, z_step_mm=.1)
        result = self.finish()
        self.assertIn('Injected read fault', result['error'])
        self.assertTrue(result['stopConfirmed'])
        self.assertEqual(len([c for c in self.commands if c[1:3] == 'PA']), 1)

    def test_context_change_stops_before_next_move(self):
        self.live_fake(mutate=True)
        self.start(repeat_count=2, z_step_mm=.1)
        self.assertIn('configuration changed', self.finish()['error'])
        self.assertEqual(len([c for c in self.commands if c[1:3] == 'PA']), 1)

    def test_mode_connection_and_activity_guards(self):
        with self.assertRaises(RuntimeError):
            line_test.start_line(self.jog, dict(mode='live'))
        self.jog.connected = False
        with self.assertRaises(RuntimeError):
            self.start()
        self.jog.connected = True
        for state in (self.jog._sensor_home_state, self.jog._run_state):
            state['running'] = True
            with self.assertRaises(RuntimeError):
                self.start()
            state['running'] = False
        self.assertIsNone(self.jog._run_thread)

    def test_starts_from_measured_pose_without_drawing_registration(self):
        self.live_fake()
        self.jog.position['y'] = 0  # Use the controller reading as the stroke origin.
        self.jog._alignment_required = True
        self.start()
        self.assertTrue(self.finish()['done'])
        self.assertEqual(self.commands, ['2VA1.000000', '2PA-11.500000', '2VA1.000000', '2PA-12.500000'])
        self.assertTrue(self.jog._alignment_required)

    def test_dispatch_status_and_progress(self):
        namespace = dict(JOG=self.jog, DEPTH_CONTEXT=app.DepthContext(), JOG_AXES=app.JOG_AXES,
                         ESP300_AXIS_SIGNS=app.ESP300_AXIS_SIGNS)
        handler = Mock(command='POST')
        handler.read_json.return_value = dict(mode='mock', repeat_count=2, z_step_mm=.1)
        with patch.object(integration, 'engine', None), patch.object(integration, 'last_context', None):
            integration.dispatch(handler, namespace, 'line-run')
            handler.send_error_json.assert_called_once()
            self.assertIsNone(self.jog._run_thread)
            handler.reset_mock()
            integration.dispatch(handler, namespace, 'line-path-run')
            handler.send_error_json.assert_not_called()
            self.assertTrue(self.finish()['done'])
            handler.command = 'GET'
            integration.dispatch(handler, namespace, 'status')
            result = handler.send_json.call_args.args[0]
            self.assertEqual(result['test_type'], 'line')
            self.assertEqual(result['state']['completed'], 6)
            self.assertEqual(result['state']['total'], 6)
            self.assertIsNone(result['upper_right'])
            with patch.object(self.jog, 'run_status', return_value=dict(running=True, index=2)):
                integration.dispatch(handler, namespace, 'status')
            self.assertEqual(handler.send_json.call_args.args[0]['state']['phase'], 'line_z_ingress')


if __name__ == '__main__':
    unittest.main(verbosity=2)
