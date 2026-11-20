"""Absolute machine Z checks without hardware or changes to operator settings."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import dwg_to_esp300 as export
import visualizer_server as app
from substrate_production import compile_trial


class ZLimitTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "z-max-mm.json"
        self.path.write_text("12.34525", encoding="utf-8")
        self.jog = app.JogController(z_limit_path=self.path)
        self.jog.connect("mock", 19200, True)

    def test_boundary_and_local_relabel(self):
        jog = self.jog
        jog.goto(120, -110, 12.34525)
        jog.set_local_home(0, 0, 0)
        self.assertEqual(jog.status()["rawPosition"]["z"], 12.34525)
        before = jog.status()
        with self.assertRaisesRegex(ValueError, "Machine Z"):
            jog.move("z", .000001, 1)
        with self.assertRaisesRegex(ValueError, "Machine Z"):
            jog.goto(0, 0, .001)
        self.assertEqual(jog.status()["rawPosition"], before["rawPosition"])
        self.assertEqual(jog.focus_trim_mm, 0)
        jog.move("x", 100, 1)
        jog.move("z", -60, 1)
        self.assertAlmostEqual(jog.raw_position["z"], -47.65475)

    def test_edit_persists_and_rejection_precedes_any_axis_command(self):
        jog = self.jog
        jog.goto(20, 20, 10)
        jog.set_local_home(0, 0, 0)
        jog.move("z", -2, 1)
        self.assertEqual(jog.set_z_max(7)["zMaxMm"], 7)
        self.assertEqual(app.JogController(z_limit_path=self.path).z_max_mm, 7)
        jog._write = Mock()
        jog.dry_run = False
        jog._read_axis_position = lambda axis: [21, -21, 6][axis-1]
        for action in (jog.home, jog.go_to_local_home, lambda: jog.goto(50, 60, 0)):
            with self.assertRaisesRegex(ValueError, "Machine Z"):
                action()
        jog._write.assert_not_called()
        for value in (None, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                jog.set_z_max(value)
        self.assertEqual(self.path.read_text().strip(), "7.0")

    def test_later_z_violation_blocks_entire_plan(self):
        jog = self.jog
        jog.move("z", 12, 1)
        xy = dict(to3=[100, 200, 1000], duration=1, speedMmS=1)
        z = dict(to3=[100, 200, 0.345251], duration=1, zOnly=True)
        with self.assertRaisesRegex(ValueError, "Machine Z"):
            jog.run_plan([xy, z])
        self.assertIsNone(jog._run_thread)
        jog.run_plan([xy])
        jog._run_thread.join(2)
        self.assertTrue(jog.run_status()["done"])
        self.assertEqual(jog.raw_position["z"], 12)

    def test_substrate_return_checks_absolute_z(self):
        with self.assertRaisesRegex(ValueError, "Machine Z"):
            compile_trial({"context": {}, "sites": []}, [3, 4, 12], 1,
                          {"right": 1, "down": 1}, self.jog, [3, 4, 12.5])

    def test_exported_script_uses_saved_limit_without_serial(self):
        file = self.path.with_suffix(".py")
        with patch.object(export, "read_z_max", return_value=12.34525):
            code = export.generate_esp300_script([], output=file, metadata={}, port="unused",
                baudrate=19200, feed_rate=1, travel_rate=1, passes=1, position_tolerance=.001,
                command_settle=0, dry_run_default=True)
        script = {"__name__": "test_export"}
        exec(compile(code, str(file), "exec"), script)
        writes = script["write_command"] = Mock()
        script["move_abs"](3, 12.34525)
        script["move_abs"](1, 100)
        self.assertEqual(writes.call_count, 2)
        with self.assertRaisesRegex(ValueError, "Machine Z"):
            script["move_abs"](3, 12.345251)
        script["CURRENT_Z"] = 12.34525
        with self.assertRaisesRegex(ValueError, "Machine Z"):
            script["move_rel"](3, .000001)
        self.assertEqual(writes.call_count, 2)
