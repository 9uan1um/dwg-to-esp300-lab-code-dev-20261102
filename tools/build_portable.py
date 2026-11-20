"""Build a source-only Windows/WSL release from a reviewed file allowlist."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
# No installed runtime, configs, backups, logs, or lab data.
FILES = (
    ".gitignore", "README.md", "requirements.txt",
    "dwg-esp300-launch.cmd", "launch_dwg_to_esp300.ps1",
    "esp300-bridge.cmd", "esp300-stop.cmd", "substrate-test.cmd",
    "launch_substrate_mock.ps1", "launch_integrated.py",
    "esp300_connection.py", "dwg_to_esp300.py", "visualizer_server.py",
    "z_limit.py", "ready_position.py", "app_audit.py", "depth_context.py",
    "depth_recipe.py", "point_test.py", "line_test.py", "circle_test.py",
    "integrated_substrate.py", "substrate_app.py", "substrate_engine.py",
    "substrate_production.py",
    "docs/portable-install.md", "docs/esp300-wsl-connection.md",
    "docs/esp300-wsl-connection.ko.md",
    "tools/check_environment.py", "tools/flw_runtime.ps1",
    "tools/setup_runtime.ps1", "tools/setup_esp300_virtualization.ps1",
    "tools/setup_esp300_linux.ps1", "tools/setup_esp300_linux.sh",
    "tools/start_esp300_bridge.ps1", "tools/stop_esp300.ps1",
    "tools/esp300_bridge_runtime.py", "tools/esp300_serial_bridge.py",
    "visualizer/app.js", "visualizer/index.html", "visualizer/styles.css",
    "visualizer/depth-review.html", "visualizer/depth-review.js",
    "visualizer/ready-controls.js", "visualizer/substrate-dialog.js",
    "visualizer/substrate/app.js", "visualizer/substrate/index.html",
    "visualizer/substrate/style.css", "visualizer/vendor/three.module.js",
    "visualizer/vendor/THREE-LICENSE.txt",
    "substrate_ui/app.js", "substrate_ui/index.html", "substrate_ui/style.css",
)

def main():
    files = tuple((name, ROOT / name) for name in FILES)
    for name, path in files:
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError(f"Missing or unsafe release input: {name}")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    target = output / "FLW-ESP300-Windows-x64-source.zip"
    manifest = {}
    with ZipFile(target, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for name, path in files:
            content = path.read_bytes()
            archive.writestr(f"FLW-ESP300/{name}", content)
            manifest[name] = hashlib.sha256(content).hexdigest()
        archive.writestr("FLW-ESP300/package-manifest.json", json.dumps(manifest, indent=2))
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n", encoding="ascii")
    print(f"Built {target} ({len(manifest)} files)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())