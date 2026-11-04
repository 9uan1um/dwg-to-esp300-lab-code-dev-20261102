# Current substrate workflow

Use **substrate-test.cmd** for the isolated interactive mock app. No automatic installation. See [SUBSTRATE_START_HERE.md](SUBSTRATE_START_HERE.md). Live operation is fail-closed. The historical instructions below are superseded for this dated branch.

# 20261102 depth experiment and application audit

## 내가 뭐라고 했고 → 그래서 이렇게 했고 → 결과는 어떻다

- 오늘 날짜 비-3D 복사본이 없으면 20261028 복사 → 현재 수정 사항을 포함한 원본 스냅샷을 별도로 복사 → `dwg-to-esp300-lab-code-dev-20261102`. 기존 원본과 `-3D` 폴더는 수정하지 않음. 파일 해시와 Git HEAD는 `COPY_BASELINE_20261102.json`.
- 왼쪽 위 원점, 오른쪽/아래 10×10 mm → 1.6 mm 간격 7×7 행 우선 지그재그, 첫 원점 제외 → 48점. 실제 점 범위는 9.6×9.6 mm이며 나머지 0.4 mm를 자동 재분배하지 않음.
- 24점씩 두 그룹, 12개 Z 목표를 두 점씩 → 각 그룹 Z 0.0–1.1 mm, 0.1 mm 간격 → 처음 24점 진입 0.4 mm/s, 다음 24점 0.1 mm/s. 모두 −0.5에서 전체 진입, 모두 1.2 mm/s로 −0.5 복귀.
- 앱 켜짐부터 종료까지 기록, center(sensor) → jog → set local home 포함 → 시작/종료/예외, HTTP 요청/응답, 컨트롤러·카메라·포커스 작업 의도/결과/오류, 전송 반환, 위치 표본, 원점/설정 변경을 JSONL로 기록 → 재생/자동 실행 기능 없음. 세부 기록 범위와 손실 한계는 아래 참조.

## Safe entry points

Open `visualizer/depth-review.html` directly as a file. It displays all 48 sites and downloads an offline JSON recipe. It does not start the application, connect hardware or call network APIs in file mode. `python -B depth_recipe.py --output offline-depth-recipe.json` generates equivalent data with exclusive-create protection. No external packages are needed for generation.

When the legacy app is deliberately operated in some future authorized session, its new read-only `/api/depth/preview` and `/api/depth/validate` endpoints bind recipes to a context snapshot. The review page can regenerate/compare that snapshot and revalidates before downloading an app-bound recipe. Local files have no live context. Context includes origin revision, offsets/home reference, connection generation, axis numbers/signs, port/baud, simulation state and configured limits. Changes invalidate previous recipes, including change-then-restore via observed revisions. Existing files outside this app and changes between observations cannot be detected automatically. Manual edits to recipes also fail validation.

`/api/depth/execute` always rejects. The existing run API rejects depth recipe documents and site records. No adapter to controller segments or executable controller code is supplied. Existing legacy 2D motion functions retain their original capabilities; this task does not authorize operating them.

## Coordinates, beam and velocity

Targets are user-defined **relative stage coordinates**, not calibrated optical depths or safe limits. X ILS150PP, Y UTS100PP, Z GTS150 and +Z deeper are user-reported. The legacy axis signs are recorded as historical configuration; right/down-to-controller signs remain explicitly unknown/unverified. No controller XYZ target is generated. Beam is assumed continuously on: XY traverse is not non-exposing or guaranteed non-modifying. XY traverse speed is unspecified. Lens clearance, material response and physical direction mapping remain unresolved.

Requested speeds are recorded in operation arguments; exact controller commands and transport-return byte counts are separate events. A write return does not prove controller acceptance or motion. Position reads yield host-timestamped per-axis finite-difference averages, not synchronized XYZ velocity, instantaneous speed, or laser-gate feedback. Fixed requested speed does not mean constant actual velocity during acceleration, corners or stops.

## Audit storage and honest coverage

Main application entry initializes `logs/app_audit/<UTC>-<session>.jsonl` before optional imports. Imports for tests do not initialize disk logging. Each process gets a new exclusive file. Events contain UTC, monotonic host time, sequence, thread and session; worker records have a SHA-256 chain. A bounded 10,000-event nonblocking queue feeds one writer; each record is flushed with `fsync`. Logging does not add controller commands, change command arguments, query extra positions or replay motion. It still consumes CPU/memory/I/O and has not been performance-qualified on hardware.

Normal Python exit drains with a bounded wait and records `app_exit`; this does **not** establish physical standstill. Forced process kill, power loss and native crashes cannot emit a shutdown event; queued events or a final partial record can be lost. `app_audit.validate_log(path)` reads the durable valid prefix, checks the chain, reports sequence gaps/partial tails and missing clean-exit markers without altering evidence. No automatic log repair or rotation is performed. Queue overflow/disk failure is visible in stderr and POST `/api/audit/status`; logging failure during operation does not alter motion return values. Failure to create the initial log aborts startup before optional application/device imports.

Recorded scope is the Python app lifetime, not the launcher/install steps, browser opening/closing or unsent UI clicks. HTTP JSON is recorded, but multipart upload contents and camera image/video frames are not copied into the journal. Cached state snapshots are not simultaneous physical telemetry. Command replies are decoded using existing behavior; malformed serial bytes discarded by legacy decoding are not recoverable. Position averages are reset on observed origin/configuration changes and suppressed during sensor-home reference transitions. Unobserved external coordinate changes may still produce discontinuities and must not be interpreted as speed. Other programs or standalone legacy scripts with no audit initialization are outside this log. Previous running app instances remain untouched and do not acquire these changes automatically. “All activity” must not be read as proof of every physical event or zero record loss.

## Verification

`run_disconnected_tests.py` puts this checkout first on the embedded runtime path, asserts the imported app location, and blocks serial opens, camera opens, socket connections and child processes before importing the app. Tests use fake controllers and in-memory HTTP handlers, with no server launch. `OFFLINE_TEST_RESULTS.txt` records the final result. Existing sensor-home/manual-home regression tests cover unchanged command behavior; depth/audit tests cover exact scheduling, context invalidation, rejection of execution, requested/sent/sample distinctions, queue overflow, disk failure, concurrency, chain corruption and partial tails.

The copy intentionally excludes runtime/venv, Git database, generated bulk, historical logs/photos and secrets. Nothing was installed. The existing Python 3.12 runtime was read and used only for guarded tests, with bytecode writing disabled. Live operation is not ready or validated.

Final offline validation: 36 tests passed, all root Python syntax checks passed, depth-review.js syntax passed, and the static review page was inspected in isolated headless Edge. The injected queue-full and disk-failure warnings in the test record are expected test cases.


