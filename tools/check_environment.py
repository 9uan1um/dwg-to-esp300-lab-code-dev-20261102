"""Import and port-enumeration check. Never opens a camera or serial port."""
import json
import sys
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import visualizer_server
import aspose.cad
from esp300_connection import list_serial_ports

print(json.dumps({
    "status": "ready", "python": sys.version.split()[0],
    "packages": {name: version(name) for name in
                 ("ezdxf", "pyserial", "numpy", "opencv-python", "aspose-cad")},
    "serialPorts": list_serial_ports(), "wslRequired": False,
    "hardwareTested": False,
}, ensure_ascii=False, indent=2))
