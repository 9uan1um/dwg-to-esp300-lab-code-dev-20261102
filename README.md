# dwg-to-esp300-lab-code-dev-20261102

November 2 development copy, including substrate point tests and depth recipes.

## Public source snapshot

Prepared on 2026-11-04 from the current local working copy. This repository starts with fresh history; runtime binaries, research data, raw experimental records, local backups, generated design-specific examples, and legacy PDF/PPTX documentation are excluded. Older documentation below may refer to those local-only files or to a portable ZIP that is not included in this repository. Use the explicit runtime setup in the new-PC guide. Generic test DXF drawings are included.

Historical base: [bbbbaig/dwg-to-esp300-lab-code](https://github.com/bbbbaig/dwg-to-esp300-lab-code), local base commit `230014b`. Existing source notices are preserved; publication does not add a new license grant.

This publication checks packaging and source syntax only. It does not certify hardware motion, optical focus, or safety. The legacy device-control app is intended for a trusted local workstation; do not expose its control API to an untrusted network.

---

# DWG/DXF to ESP300 laser path

This project turns CAD geometry into an ESP300 stage-control Python script.
It follows the style of `ESP300_Controller.ipynb`: serial commands such as
`1PA...`, `2PA...`, `1VA...`, and `2VA...` are generated for the X/Y stage.

## Run on another Windows PC

The current build keeps the camera and manual tools; automatic focus is inactive.

Install the repository or extract the Windows x64 source ZIP completely, then
follow [the new-PC guide](docs/portable-install.md) for the explicit local Python
setup, hardware-free check, local safety calibration and optional WSL2 bridge.
The source ZIP does not contain installed runtimes or machine calibration.
한국어 ESP300 연결 절차는 [WSL 연결 설명서](docs/esp300-wsl-connection.ko.md)를 참고하세요.

The verified 99-outline Aspose evaluation mark is excluded from motion-path
extraction by the existing SKIP_KNOWN_ASPOSE_WATERMARK setting. Recognition is
limited to the exact verified outline geometry; unrelated small design features
are preserved. Source DWG/DXF files are not modified.

## Generate code from the sample DWG

The generated stage coordinates are always in millimeters. For the sample DWG,
the longest side is calibrated to 25 mm, which also makes the circular holes
about 2 mm in diameter.

```powershell
py dwg_to_esp300.py `
  "C:\path\to\drawing.dwg" `
  --output adjust25design_esp300.py `
  --preview adjust25design_preview.svg `
  --fit-longest-mm 25 `
  --origin-x 0 `
  --origin-y 0 `
  --feed-rate 0.4 `
  --travel-rate 1.0 `
  --passes 1 `
  --ipynb
```

Generated files:

- `adjust25design_esp300.py`: executable ESP300 motion script
- `adjust25design_esp300.ipynb`: Jupyter notebook version when `--ipynb` is used
- `adjust25design_preview.svg`: path preview in machine millimeters
- `adjust25design.converted.dxf`: intermediate DXF when the input is DWG

Use `--notebook-output path\to\job.ipynb` if you want to choose the notebook
path explicitly.

## Run the generated machine script

Open and inspect the generated script first. The generated file now follows the
notebook style: `send()`, `move_abs()`, `move_rel()`, and `set_velocity()` are
top-level functions. Repeated cuts are stored as `PASSES = 5` when all selected
paths share the same count, or as per-path `passes` when they differ. The laser
hooks are intentionally no-ops unless you fill in laser trigger commands.
Default live speeds follow the field notebooks conservatively: `0.4 mm/s` for
cutting, `1.0 mm/s` for travel, and `0.3 mm/s` for Z motion.

```powershell
py adjust25design_esp300.py --dry-run
py adjust25design_esp300.py --live --port COM5
py adjust25design_esp300.py --live --port COM5 --passes 2
```

In Jupyter, open the generated `.ipynb`, run the setup cells, inspect
`METADATA`, and only set `LIVE_RUN = True` after checking the preview, COM port,
pass count, speed, and laser trigger commands.

## Visualize the generated movement

```powershell
py visualizer_server.py --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

The visualizer reads the generated ESP300 scripts and animates the exact move
sequence. The full drawing view shows the 25.000 mm side; the outline view uses
only the `외형선(ISO)` layer.

The browser interface can now trace a new DWG/DXF directly:

- Choose a `.dwg` or `.dxf` file and press `Trace File`, or paste a local
  drawing path and press `Trace Path`.
- Use `직접 조합` to build paths without CAD. `빈 작업` starts an empty mm
  workspace, then add `직선`, `사각형`, or a fixed 2 mm `원`.
- `긴 변(mm)` sets the real-world size of the longest side. Use `25` for the
  current sample.
- Coordinates are generated in mm, and the circular-hole check is fixed at
  2 mm so it cannot be changed accidentally.
- Select paths from the canvas or the path list.
- Set pass counts per path, or use the global pass box and `Apply`.
- Keep `Optimize` enabled to reorder selected paths and repeated passes to
  reduce laser-off travel.
- Press `코드 다운로드` to write the selected plan under `generated/` and
  download the generated ESP300 Python file in the browser.

By default, generated path order is optimized to reduce laser-off travel moves.
Use `--no-optimize` only when you need to preserve the original CAD entity order.
By default, `--trace-mode design` excludes obvious watermark/support geometry
such as `layer 0` evaluation text and full-page diagonal strokes. Use
`--trace-mode all` only when you intentionally want every CAD entity.

## Notes

### Stage Y direction

On this rig, positive logical Y means upward, while ESP300 axis 2 increases
downward. `ESP300_AXIS_SIGNS` in `esp300_connection.py` is therefore
`{"x": 1, "y": -1, "z": 1}`. Manual jog, absolute moves, local-home alignment,
path execution and position readback use this same coordinate transform.
New exports embed the direction mapping for both commands and readback.

After updating, restart the Python web server (refreshing the browser alone
does not reload Python), reconnect, and set local home again at the sample
reference. With no local-home offset, displayed Y is the negative of the
controller's Y reading. Previously exported Python files and notebooks must
be exported again to receive this correction.

Hardware-free regression check:
`python -m unittest test_axis_direction test_esp300_bridge.AxisMappingTests -v`.
Physical upward/downward motion still needs confirmation on the rig.

### Focus camera on this PC

The Windows Python server opens the camera with OpenCV's Media Foundation
backend (`CAP_MSMF`). The browser displays `/api/camera/stream` (MJPEG); it
does not use `getUserMedia` or a camera file path. Open **Focus camera (UVC)**,
set **Index** and press **Connect**.

Verified on 2026-10-27: index `0` is **LGE Camera**, index `1` is
**Mirametrix Virtual Camera**, and index `2` is **USB2.0 UVC PC Camera**
(`05E3:0510`). The external camera supplies 640 x 480 frames at index `2`.
Index `1` repeats a static camera-unavailable icon; the frozen-frame watchdog
disconnects it after about five seconds. The UI and camera API now default to
`2`; the browser remembers the last index that actually supplied video.
Device numbering can change after device/driver changes, so recheck it if
the camera stops responding. A dark image with changing brightness values
means frames are arriving; check illumination and the optical path separately.

The camera selection is in `visualizer/index.html` and `visualizer/app.js`;
`CameraController.connect()` in `visualizer_server.py` opens that index.
It verifies that the device supplies a frame before reporting success, and
reports a reason in the camera panel if capture fails or stops updating.

The live picture has a fixed overlay of 15 square cells across. Cell size is
the displayed picture width divided by 15, with rows starting at the picture's
top edge and a partial row at the bottom when needed. It follows resizing and
the enlarged jog view, excludes letterbox bars, and lets target-selection clicks
through. The grid is a visual movement reference with no distance calibration;
it does not alter camera frames.

- DWG input is converted to DXF automatically with ODA File Converter when it is
  installed. If ODA is not found, the script tries `aspose-cad`.
- DXF input is parsed directly with `ezdxf`.
- The converter supports common curve geometry through `ezdxf.path.make_path`,
  including lines, polylines, arcs, circles, ellipses, and splines when `ezdxf`
  can flatten them.
- `--include-layer` and `--exclude-layer` accept shell-style wildcards.
