"""Editable maximum ESP300 machine Z in millimetres."""
import json
import math
import os
import tempfile
from pathlib import Path

Z_MAX_FILE = Path(__file__).resolve().parent / "config" / "z-max-mm.json"


def validate_z_max(value):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("기계 Z 상한에 유한한 숫자를 입력하세요.")
    return float(value)


def read_z_max(path=Z_MAX_FILE):
    try:
        return validate_z_max(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "Machine Z limit is not configured; see docs/portable-install.md. No live motion is allowed."
        ) from error


def save_z_max(path, value):
    value = validate_z_max(value)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return value


def check_z_target(raw_z, maximum):
    # Check both the requested position and the six-decimal ESP300 PA command.
    if not math.isfinite(raw_z) or raw_z > maximum or float(f"{raw_z:.6f}") > maximum:
        raise ValueError(f"Machine Z target {raw_z:.9g} mm exceeds the absolute Z limit {maximum} mm.")
