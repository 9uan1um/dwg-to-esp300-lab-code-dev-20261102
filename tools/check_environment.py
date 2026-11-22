"""Hardware-free source and dependency checks; never open or enumerate devices."""
import importlib
import json
import sys
from importlib.metadata import version
from pathlib import Path

root = Path(__file__).resolve().parents[1]
modules = ("ezdxf", "serial", "numpy", "cv2", "aspose.cad")
required = (
    "visualizer_server.py", "dwg_to_esp300.py", "esp300_connection.py",
    "z_limit.py", "ready_position.py", "point_test.py", "line_test.py", "circle_test.py",
    "depth_context.py", "integrated_substrate.py", "substrate_production.py",
    "substrate_engine.py", "substrate_app.py", "launch_integrated.py",
    "tools/esp300_bridge_runtime.py", "tools/esp300_serial_bridge.py",
)
for name in modules:
    importlib.import_module(name)
for name in required:
    compile((root / name).read_bytes(), name, "exec")

print(json.dumps({
    "status": "ready", "python": sys.version.split()[0],
    "packages": {name: version(name) for name in
                 ("ezdxf", "pyserial", "numpy", "opencv-python", "aspose-cad")},
    "checkedSourceFiles": len(required), "serialPorts": [],
    "wslRequired": False, "hardwareTested": False,
    "machineCalibrationChecked": False,
}, ensure_ascii=False, indent=2))