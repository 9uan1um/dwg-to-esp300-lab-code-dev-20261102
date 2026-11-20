"""Drawing depth from an imported DXF through planning, mock motion and export."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import visualizer_server as app


class DrawingDepthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.session = app.trace_file(app.ROOT / "drawings" / "focus_test_line.dxf", {})
        cls.path_id = cls.session["paths"][0]["id"]

    def plan(self, **settings):
        return app.build_plan(self.session, {"paths": [{"id": self.path_id, "passes": 11}], **settings})

    def test_zero_keeps_default_plan(self):
        segments = self.plan()["segments"]
        self.assertEqual(segments, self.plan(drawingDepthMm=0)["segments"])
        self.assertEqual([s["to3"][2] for s in segments[:4]], [-1, -1, 0, 0])

    def test_entry_repeats_and_clearance(self):
        segments = self.plan(drawingDepthMm=.125)["segments"]
        self.assertEqual([(s["kind"], s["to3"][2]) for s in segments[:3]],
                         [("z-defocus", -1), ("travel", -1), ("z-focus", .125)])
        cuts = [s["to3"][2] for s in segments if s["kind"] == "cut"]
        self.assertEqual(cuts, [.125] * 10 + [.124])
        self.assertEqual(segments[-1]["to3"][2], -1)

    def test_invalid_depth(self):
        for value in (-.001, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.plan(drawingDepthMm=value)

    def test_mock_run_uses_local_zero_and_checks_machine_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            limit = Path(directory) / "z-max.json"
            limit.write_text("10.125")
            jog = app.JogController(z_limit_path=limit)
            jog.connect("mock", 19200, True)
            jog.goto(0, 0, 10)
            jog.set_local_home(0, 0, 0)
            with self.assertRaisesRegex(ValueError, "Machine Z"):
                jog.run_plan(self.plan(drawingDepthMm=.126)["segments"])
            self.assertIsNone(jog._run_thread)
            segments = self.plan(drawingDepthMm=.125)["segments"]
            jog.run_plan(segments, record_diagnostics=True)
            jog._run_thread.join(5)
            self.assertTrue(jog.run_status()["done"])
            cuts = [r["targetRaw"]["z"] for r in jog._run_records
                    if r.get("kind") == "cut" and r.get("event") == "segment_start"]
            self.assertEqual(cuts, [10.125] * 10 + [10.124])
            self.assertEqual(jog.raw_position["z"], 9)

    def test_downloaded_code_honors_one_micron_entry(self):
        handler = Mock()
        handler.read_json.return_value = {"sessionId": self.session["id"], "drawingDepthMm": .001}
        with tempfile.TemporaryDirectory() as directory, patch.object(app, "GENERATED_ROOT", Path(directory)):
            app.VisualizerHandler.handle_export(handler)
            response = handler.send_json.call_args.args[0]
            namespace = {"__name__": "offline_export"}
            script = Path(response["scriptPath"])
            exec(compile(script.read_bytes(), str(script), "exec"), namespace)
        namespace["move_abs"] = Mock()
        namespace["set_focus_reference"](10)
        namespace["prepare_cut_start"](*namespace["CURRENT_XY"], 1)
        namespace["move_abs"].assert_called_with(namespace["AXIS_Z"], 10.001)
        self.assertEqual(namespace["defocus_target_z"](), 9)
