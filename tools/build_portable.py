"""Build a redistributable ZIP from an explicit application-only allowlist."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
# No .git, uploads, lab data, research, cached conversions or diagnostic images.
FILES = (
    "dwg-esp300-launch.cmd", "launch_dwg_to_esp300.ps1", "esp300-bridge.cmd",
    "esp300-stop.cmd", "README.md", "requirements.txt", "esp300_connection.py",
    "dwg_to_esp300.py", "visualizer_server.py", "focus_autocal.py",
)
DIRECTORIES = ("visualizer", "tools", "docs", "drawings", "example", "runtime")


def package_files():
    for name in FILES:
        yield ROOT / name
    for name in DIRECTORIES:
        for path in sorted((ROOT / name).rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                # Developer scripts and tests are available from the repository.
                if name == "tools" and (path.name.startswith("test_") or "diagnostics" in path.parts):
                    continue
                yield path


def main():
    marker = ROOT / "runtime" / "requirements.sha256"
    expected = hashlib.sha256((ROOT / "requirements.txt").read_bytes()).hexdigest()
    if not marker.is_file() or marker.read_text().strip().lower() != expected:
        raise RuntimeError("Prepare the runtime using dwg-esp300-launch.cmd -Check first")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    target = output / "FLW-ESP300-Windows-x64.zip"
    manifest = {}
    with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in package_files():
            relative = path.relative_to(ROOT).as_posix()
            if path.is_symlink():
                raise RuntimeError(f"Refusing symlink: {relative}")
            archive.write(path, f"FLW-ESP300/{relative}")
            manifest[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
        archive.writestr("FLW-ESP300/package-manifest.json", json.dumps(manifest, indent=2))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n", encoding="ascii")
    print(f"Built {target} ({target.stat().st_size / 1024**2:.1f} MiB, {len(manifest)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
