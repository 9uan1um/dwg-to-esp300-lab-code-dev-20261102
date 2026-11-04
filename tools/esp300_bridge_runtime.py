"""Linux bridge discovery without shell-embedded Python or device I/O."""
from __future__ import annotations

import argparse
import errno
import json
import os
import signal
import socket
import time
from pathlib import Path

from serial.tools import list_ports


def find_device(timeout=5.0):
    deadline = time.monotonic() + timeout
    while True:
        devices = [p.device for p in list_ports.comports() if (p.vid, p.pid) == (0x067B, 0x2303)]
        if len(devices) == 1:
            return devices[0]
        if len(devices) > 1 or time.monotonic() >= deadline:
            raise RuntimeError(f"Expected exactly one PL2303 adapter, found: {devices}. Check usbipd attach and the USB cable.")
        time.sleep(0.1)


def bridge_status(device, port):
    # Binding checks occupancy without accepting a connection or opening USB.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError as error:
            if error.errno != errno.EADDRINUSE:
                raise
        else:
            return {"running": False, "compatible": False}
    expected_script = Path(__file__).with_name("esp300_serial_bridge.py").resolve()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = entry.joinpath("cmdline").read_bytes().decode().rstrip("\0").split("\0")
            # Resolve relative argv paths using that process's working directory.
            cwd = entry.joinpath("cwd").resolve(strict=True)
            script = next((arg for arg in args[1:] if arg.endswith("esp300_serial_bridge.py")), None)
            if script is None or (cwd / script).resolve() != expected_script:
                continue
            active_port = int(args[args.index("--port") + 1]) if "--port" in args else 22170
            if active_port != port:
                continue
            active_device = args[args.index("--device") + 1]
            return {"running": True, "compatible": active_device == device,
                    "pid": int(entry.name), "device": active_device, "port": port}
        except (OSError, ValueError, IndexError, UnicodeError):
            continue
    return {"running": True, "compatible": False, "error": "Port is occupied by another process"}


def stop_bridge(port=22170):
    """Stop only this repository's identified bridge, never an unknown listener."""
    status = bridge_status(None, port)
    if not status["running"]:
        return {"stopped": True, "alreadyStopped": True, "port": port}
    pid = status.get("pid")
    if pid is None:
        raise RuntimeError(f"Refusing to stop an unidentified listener on {port}: {status}")
    for sig, wait_seconds in ((signal.SIGINT, 5), (signal.SIGTERM, 3)):
        current = bridge_status(None, port)
        if not current["running"]:
            return {"stopped": True, "pid": pid, "port": port}
        if current.get("pid") != pid:
            raise RuntimeError("Bridge port owner changed; stop cancelled")
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if not bridge_status(None, port)["running"]:
                return {"stopped": True, "pid": pid, "port": port}
            time.sleep(0.1)
    raise RuntimeError(f"Bridge PID {pid} did not stop")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--find-device", action="store_true")
    parser.add_argument("--check-server", metavar="DEVICE")
    parser.add_argument("--stop-server", action="store_true")
    parser.add_argument("--port", type=int, default=22170)
    options = parser.parse_args()
    if options.stop_server:
        print(json.dumps(stop_bridge(options.port)))
    elif options.find_device:
        print(json.dumps({"device": find_device()}))
    elif options.check_server:
        print(json.dumps(bridge_status(options.check_server, options.port)))
    else:
        parser.error("Choose --find-device, --check-server DEVICE or --stop-server")
