"""Shared serial setup and a non-motion ESP300 version probe."""
from __future__ import annotations


import argparse
import json
import time
import app_audit

import serial
from serial.tools import list_ports

WSL_PORT = "rfc2217://127.0.0.1:22170"
# Shared by manual jog, plan execution and newly exported scripts.
# User-confirmed logical axes (2026-10-27): ILS150PP=X, UTS100PP=Y, GTS150=Z.
# Logical Z is not inferred from the stage's physical vertical orientation.
ESP300_AXES = {"x": 1, "y": 2, "z": 3}
AXIS_MAPPING_CONFIRMED = True
# Logical positive Y is upward on this rig; controller axis 2 increases down.
# Apply this at the coordinate boundary, including position readback.
ESP300_AXIS_SIGNS = {"x": 1, "y": -1, "z": 1}


def list_serial_ports() -> list[dict]:
    """Enumerate Windows/native ports without opening or probing any device."""
    return [
        {"device": p.device, "description": p.description or p.device,
         "vid": p.vid, "pid": p.pid,
         "knownAdapter": (p.vid, p.pid) == (0x067B, 0x2303)}
        for p in sorted(list_ports.comports(), key=lambda p: p.device)
    ]


def open_esp300(port: str, baudrate: int = 19200):
    # RFC2217 carries both data and hardware flow-control settings to Linux.
    # pySerial's RFC2217 implementation does not support write_timeout.
    options = {} if port.lower().startswith("rfc2217://") else {"write_timeout": 2}
    return serial.serial_for_url(
        port, baudrate=int(baudrate), bytesize=serial.EIGHTBITS,
        parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
        timeout=0.1, rtscts=True, **options,
    )


def read_version(connection, timeout: float = 3.0) -> str:
    """Read VE using a caller-owned connection; never close it or send motion."""
    connection.reset_input_buffer()
    app_audit.emit("command_intent", command="VE", purpose="version_query")
    accepted = connection.write(b"VE\r")
    app_audit.emit("transport_write_return", command="VE", bytes_accepted=accepted,
                   meaning="Transport return only; not controller acknowledgement")
    reply = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(reply) < 1024:
        part = connection.read(1)
        if part in (b"\r", b"\n"):
            if reply:
                break
        else:
            reply.extend(part)
    else:
        raise RuntimeError("No complete VE reply. Check ESP300 baud rate, RS-232 connection and RTS/CTS.")
    text = reply.decode("ascii", errors="strict").strip()
    app_audit.emit("controller_response", command="VE", response=text)
    if not text or text == "VE":
        raise RuntimeError(f"Received an echo/empty reply, not a controller version: {text!r}")
    return text


def probe_version(port: str, baudrate: int = 19200, timeout: float = 3.0) -> dict:
    """Send only VE (version). Never enable, disable, home, or move axes."""
    with open_esp300(port, baudrate) as connection:
        return {"port": port, "baudrate": baudrate, "versionReply": read_version(connection, timeout),
                "command": "VE", "connectionKeptOpen": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Read ESP300 version only; no motion or motor commands.")
    parser.add_argument("--port", default=WSL_PORT)
    parser.add_argument("--baudrate", type=int, default=19200)
    args = parser.parse_args()
    print(json.dumps(probe_version(args.port, args.baudrate), ensure_ascii=False))
