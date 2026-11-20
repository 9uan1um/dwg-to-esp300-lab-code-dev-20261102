from __future__ import annotations

# Pin this copy when using the original embedded runtime.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent))


# Start before optional imports, so startup/import failures are recorded too.
import app_audit
if __name__ == "__main__":
    from pathlib import Path as _AuditPath
    app_audit.start(_AuditPath(__file__).resolve().parent / "logs" / "app_audit")

from depth_recipe import build_recipe, validate_recipe
from depth_context import DepthContext
DEPTH_CONTEXT = DepthContext()

import argparse
import cgi
import csv
import copy
import importlib.util
import json
import math
import mimetypes
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import cv2
import numpy as np
import serial
from z_limit import Z_MAX_FILE, check_z_target, read_z_max, save_z_max
from esp300_connection import AXIS_MAPPING_CONFIRMED, ESP300_AXES, ESP300_AXIS_SIGNS, open_esp300, probe_version, read_version, list_serial_ports
from ready_position import ReadyPositionStore, prepare_ready_locked

# MSMF backend spams a C++ warning on every failed grabFrame (e.g. camera
# unplugged) with no Python-side rate limit -- left running overnight this
# fills a log file at ~25 lines/sec. Silence it; failures are still handled
# in CameraController._capture_loop below.
if hasattr(cv2, "setLogLevel"):
    cv2.setLogLevel(0)
else:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_SILENT)

from dwg_to_esp300 import (
    LaserPath,
    apply_fit_scale,
    cap_scale_to_circle,
    decode_dxf_unicode_escapes,
    distance,
    ensure_dxf,
    extract_paths,
    generate_esp300_script,
    orient_path_from_current,
    raw_bbox,
    rotate_paths,
    select_design_paths,
    skip_known_aspose_watermark,
    transform_paths,
    write_preview_svg,
)


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "visualizer"
UPLOAD_ROOT = ROOT / "uploads"
GENERATED_ROOT = ROOT / "generated"
DEFAULT_SOURCE = ROOT / "drawings" / "Centered_Square_10mm.dxf"
DEFAULT_LONGEST_SIDE_MM = 25.0
DEFAULT_ROTATION_DEG = 45.0
FIXED_REFERENCE_CIRCLE_DIAMETER_MM = 2.0
DEFAULT_FEED_RATE_MM_S = 0.4
DEFAULT_TRAVEL_RATE_MM_S = 1.0
DEFAULT_FOCUS_Z_MM = 0.0
DEFAULT_Z_DEFOCUS_MM = 1.0
DEFAULT_Z_SPEED_MM_S = 0.3
Z_STEP_BACK_PASSES = 10
Z_STEP_BACK_MM = 0.001
DEFAULT_COMMAND_SETTLE_S = 0.05
DEFAULT_POSITION_TOLERANCE_MM = 0.003
DEFAULT_GLASS_SIZE_MM = (25.0, 25.0)
DEFAULT_USABLE_MARGIN_MM = 0.05
CURVE_FLATTENING_SCALE_HINT = 25.4
SCRIPT_CHOICES = {
    "full": ROOT / "example" / "adjust25design_esp300.py",
    "outline": ROOT / "example" / "adjust25design_outline_esp300.py",
}

SESSIONS: dict[str, dict] = {}

JOG_AXES = ESP300_AXES
JOG_DEFAULT_BAUDRATE = 19200
JOG_MOTOR_SETTLE_S = 0.05
JOG_TP_RETRIES = 5
JOG_TP_RETRY_DELAY = 0.08
JOG_SPEED_MAX_MM_S = 10.0
JOG_HOME_SPEED_MM_S = 5.0
JOG_HOME_TIMEOUT_S = 60.0
JOG_MANUAL_TIMEOUT_MIN_S = 5.0
JOG_MANUAL_SETTLE_S = 0.5
JOG_NOOP_TOLERANCE_MM = 1e-6  # Request equality, NOT the 0.02 mm arrival tolerance.
# Central origin search: ILS/GTS have an encoder index; UTS-PP does not.
SENSOR_HOME_AXES = {"x": ("M-ILS150PP", 1), "y": ("UTS100PP", 2), "z": ("GTS150", 1)}
SENSOR_HOME_HIGH_MM_S = 1.0
SENSOR_HOME_LOW_MM_S = 0.1
SENSOR_HOME_TIMEOUT_S = 300.0  # per axis; failure aborts the entire sequence
JOG_POSITION_PATTERN = re.compile(r"[-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?")


JOG_RUN_STOP_TIMEOUT_S = 5.0
JOG_RUN_PASSIVE_POLL_S = 0.75


class MotionNotStopped(RuntimeError):
    pass


class RunStopRequested(Exception):
    """Internal control flow; a user stop is not a completed segment."""


class SerialCommError(RuntimeError):
    """The serial port itself failed (raised by _write/_query on a real
    serial.SerialException), as opposed to a transient bad/missing reply
    from the controller. Callers that retry on a generic RuntimeError
    (expecting the latter) must let this one propagate instead -- retrying
    against a dead port for a whole deadline just delays and mislabels the
    eventual failure as an unrelated timeout."""

CAMERA_FREEZE_LOG_PATH = ROOT / "camera_freeze_log.csv"
SERIAL_RETRY_LOG_PATH = ROOT / "serial_retry_log.csv"


def _append_csv_row(path: Path, header: list[str], row: list) -> None:
    """Shared best-effort CSV append: write `header` only if the file is
    new, then append `row`. Logging is diagnostic, never load-bearing --
    a disk hiccup here must not break whatever real operation triggered it."""
    try:
        is_new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if is_new:
                writer.writerow(header)
            writer.writerow(row)
    except OSError:
        pass


CONNECTION_LOCK = threading.Lock()
CONNECTION_PREPARATION = {"active": False, "phase": None, "error": None}


class JogController:
    """Manual jog interface for the ESP300 stage controller over serial.

    Jog and planned Z moves use the absolute machine Z ceiling.
    """

    def __init__(self, ready_path=None, z_limit_path=Z_MAX_FILE) -> None:
        self._lock = threading.Lock()
        self.z_limit_path = z_limit_path
        self.z_max_mm = read_z_max(z_limit_path)
        self.ready_position = ReadyPositionStore(ready_path or ROOT / 'config' / 'ready-position.json')
        self.ser: serial.Serial | None = None
        self.dry_run = True
        self.connected = False
        self.port = ""
        self.baudrate = JOG_DEFAULT_BAUDRATE
        self.position = {"x": 12.5, "y": 12.5, "z": 0.0}
        self.raw_position = {name: ESP300_AXIS_SIGNS[name] * value for name, value in self.position.items()}
        self.local_offset = {"x": 0.0, "y": 0.0, "z": 0.0}
        self.home_ref = dict(self.position)
        # Physical calibration reference for substrate registration and focus trim.
        self.z_home_raw = 0.0
        self.focus_trim_mm = 0.0
        self._poll_generation = 0
        self._run_thread: threading.Thread | None = None
        self._run_stop = threading.Event()
        self._run_state = {"running": False, "index": 0, "total": 0, "error": None, "done": False}
        self._run_segments: list[dict] = []
        self._run_origins: dict[int, dict] = {}
        self._run_context: tuple | None = None
        self._run_pause_raw: dict | None = None
        self._run_stop_sent = False
        self._run_stop_error: str | None = None
        self._run_passive_at = 0.0
        self._run_recording = False
        self._run_record_id: str | None = None
        self._run_records: list[dict] = []
        self._run_started_at = 0.0
        self._run_elapsed_final: float | None = None
        self._sensor_home_stop = threading.Event()
        self._sensor_home_thread: threading.Thread | None = None
        self._sensor_home_state = {"running": False, "axis": None, "completed": [], "done": False, "error": None}
        self._alignment_required = False
        self._manual_target_raw: dict | None = None
        self._manual_deadline = 0.0
        self._manual_stationary_since: float | None = None
        self._manual_stop_deadline: float | None = None
        self._manual_error: str | None = None
        self._telemetry_error: str | None = None
        self._telemetry_at: float | None = None

    def _require_no_sensor_home_locked(self) -> None:
        if self._sensor_home_state["running"]:
            raise RuntimeError("Central sensor homing is in progress. Use STOP to abort it.")

    def _require_no_run_locked(self, allow_connection: bool = False) -> None:
        if CONNECTION_PREPARATION["active"] and not allow_connection:
            raise RuntimeError("Connection preparation is in progress. Wait before moving.")
        if self._run_state["running"]:
            raise RuntimeError("A planned path is running or stopping. Stop it and wait for confirmed standstill first.")

    def _require_manual_still_locked(self) -> None:
        if self._manual_target_raw is not None:
            raise RuntimeError("A manual move is still in progress. Wait for measured arrival first.")

    def _track_manual_target_locked(self, target: dict, speed: float) -> None:
        duration = max(abs(raw - self.raw_position[n]) for n, raw in target.items()) / max(.01, speed)
        self._manual_target_raw = dict(target)
        self._manual_deadline = time.monotonic() + max(JOG_MANUAL_TIMEOUT_MIN_S, duration * 2 + 2)
        self._manual_stationary_since = None
        self._manual_stop_deadline = None
        self._manual_error = None

    def _check_manual_motion_locked(self) -> None:
        """Bound manual waits; only release a move after verified standstill."""
        now = time.monotonic()
        try:
            states = [self._query(f"{axis}MD?").strip() for axis in JOG_AXES.values()]
            stationary = all(state == "1" for state in states)
        except Exception as exc:
            stationary = False
            states = [str(exc)]
        arrived = all(abs(self.raw_position[n] - raw) <= .02 for n, raw in self._manual_target_raw.items())
        if stationary and (arrived or self._manual_stop_deadline is not None):
            self._manual_target_raw = None
            self._manual_stop_deadline = None
            self._manual_stationary_since = None
            return
        if stationary:
            if self._manual_stationary_since is None:
                self._manual_stationary_since = now
            if now - self._manual_stationary_since >= JOG_MANUAL_SETTLE_S:
                self._manual_error = "Manual move stopped before reaching its target. Check the controller and retry the intended move."
                self._manual_target_raw = None
                return
        else:
            self._manual_stationary_since = None
        if self._manual_stop_deadline is not None:
            if now >= self._manual_stop_deadline:
                self._manual_error = "Manual move timed out; physical standstill is unconfirmed. Use the physical controller stop before reconnecting."
                self._telemetry_error = self._manual_error
                self._alignment_required = True
                self._disconnect_locked()
        elif now >= self._manual_deadline:
            self._manual_error = f"Manual move timed out waiting for arrival (MD={states}); stop requested."
            self._manual_stop_deadline = now + JOG_RUN_STOP_TIMEOUT_S
            try:
                self._write("ST")  # Retain holding power; never substitute AB/MF.
            except Exception as exc:
                self._manual_error += f" Stop command failed: {exc}"

    def _run_context_locked(self) -> tuple:
        return (self._poll_generation, tuple(self.local_offset.items()), tuple(self.home_ref.items()))

    def _write(self, cmd: str) -> None:
        if self.dry_run or self.ser is None:
            return
        try:
            accepted = self.ser.write((cmd + "\r\n").encode("ascii"))
            app_audit.emit("transport_write_return", command=cmd, bytes_accepted=accepted,
                           meaning="Transport return only; not controller acknowledgement or actual velocity")
        except (serial.SerialException, OSError) as exc:
            raise SerialCommError(f"Serial write failed for {cmd!r}: {exc}") from exc

    def _query(self, cmd: str) -> str:
        if self.dry_run or self.ser is None:
            return ""
        try:
            self.ser.reset_input_buffer()
            accepted = self.ser.write((cmd + "\r\n").encode("ascii"))
            app_audit.emit("transport_write_return", command=cmd, bytes_accepted=accepted,
                           meaning="Transport return only; not controller acknowledgement or actual velocity")
            # Poll without a fixed pre-delay, but require a line terminator
            # (\r or \n) before treating the reply as complete. A reply spanning
            # multiple USB-serial read chunks can otherwise be read as complete
            # after only a partial chunk, leaving trailing bytes in the buffer
            # that corrupt the next query's response.
            response = b""
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                if self.ser.in_waiting > 0:
                    response += self.ser.read(self.ser.in_waiting)
                    if b"\r" in response or b"\n" in response:
                        time.sleep(0.002)
                        if self.ser.in_waiting > 0:
                            response += self.ser.read(self.ser.in_waiting)
                        break
                else:
                    time.sleep(0.003)
        except (serial.SerialException, OSError) as exc:
            raise SerialCommError(f"Serial I/O failed for {cmd!r}: {exc}") from exc
        return response.decode("ascii", errors="ignore").strip()

    def _read_axis_position(self, axis: int, interrupt_on_stop: bool = False) -> float:
        # A real serial.SerialException used to propagate straight out of
        # here on the very first occurrence, and every caller treated that
        # as "the port died" -- torn down the whole connection (see
        # SerialCommError handling in _poll_loop / _run_worker). But a lone
        # transient I/O hiccup on a still-good, still-open handle (one
        # dropped/garbled USB-serial read among the thousands a long "run on
        # machine" job generates) looks identical to a truly severed port at
        # that first exception. Folding SerialCommError into the SAME retry
        # budget as a bad/garbled reply -- instead of only retrying parse
        # mismatches -- means one bad round-trip no longer nukes an
        # otherwise-healthy connection mid-run; only a run of JOG_TP_RETRIES
        # consecutive real failures (parse or I/O) still gives up and
        # surfaces the error, which is what an actually-dead port looks like.
        last = ""
        last_comm_error: SerialCommError | None = None
        comm_error_attempts = 0
        for attempt in range(JOG_TP_RETRIES):
            if interrupt_on_stop and self._run_stop.is_set():
                raise RunStopRequested()
            try:
                last = self._query(f"{axis}TP")
                last_comm_error = None
            except SerialCommError as exc:
                last_comm_error = exc
                comm_error_attempts += 1
            else:
                match = JOG_POSITION_PATTERN.fullmatch(last.strip())
                # Discard out-of-range values (parsing/framing artifacts) rather
                # than accepting them; the configured travel range is well
                # under 200 mm on every axis.
                if match and abs(float(match.group())) <= 250.0:
                    if comm_error_attempts:
                        # Recovered within the retry budget -- log it so a
                        # pattern of frequent transient hiccups is visible in
                        # data instead of only ever showing up as "it just
                        # disconnected sometimes" with nothing to point at.
                        _append_csv_row(
                            SERIAL_RETRY_LOG_PATH,
                            ["timestamp_utc", "axis", "comm_error_attempts", "outcome"],
                            [datetime.now(timezone.utc).isoformat(timespec="seconds"), axis, comm_error_attempts, "recovered"],
                        )
                    return float(match.group())
            if attempt < JOG_TP_RETRIES - 1:
                time.sleep(JOG_TP_RETRY_DELAY)
        if last_comm_error is not None:
            _append_csv_row(
                SERIAL_RETRY_LOG_PATH,
                ["timestamp_utc", "axis", "comm_error_attempts", "outcome"],
                [datetime.now(timezone.utc).isoformat(timespec="seconds"), axis, comm_error_attempts, "failed"],
            )
            raise last_comm_error
        raise RuntimeError(f"Axis {axis} position read failed; last reply={last!r}")

    def _raw_of(self, name: str, local_value: float) -> float:
        """Local (reported/design) coordinate -> true machine coordinate."""
        return ESP300_AXIS_SIGNS[name] * local_value + self.local_offset[name]

    def _local_of(self, name: str, raw_value: float) -> float:
        """True machine coordinate -> local (reported/design) coordinate."""
        return ESP300_AXIS_SIGNS[name] * (raw_value - self.local_offset[name])

    def set_z_max(self, value):
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            self._require_manual_still_locked()
            self.z_max_mm = save_z_max(self.z_limit_path, value)
            return self._status_locked()

    def _check_segment_z(self, segment):
        if "z" in self._segment_axes(segment):
            raw_z = (segment["readyRaw"]["z"] if segment.get("readyMove")
                     else self._raw_of("z", float(segment["to3"][2])))
            check_z_target(raw_z, self.z_max_mm)

    @staticmethod
    def _segment_axes(segment):
        if segment.get("readyMove"):
            return segment["readySelected"]
        for name in ("z", "x", "y"):
            if segment.get(name + "Only"):
                return name
        return "xy"

    def _status_locked(self) -> dict:
        return {
            "connected": self.connected,
            "dryRun": self.dry_run,
            "port": self.port,
            "baudrate": self.baudrate,
            "axisMap": dict(JOG_AXES),
            "axisSigns": dict(ESP300_AXIS_SIGNS),
            "axisMappingConfirmed": AXIS_MAPPING_CONFIRMED,
            "position": dict(self.position),
            "rawPosition": dict(self.raw_position),
            "run": dict(self._run_state),
            "localOffset": dict(self.local_offset),
            "ready": {**self.ready_position.status(),
                      "run": dict(self._run_state) if self._run_state.get('readyAxes') else None},
            "connectionPreparation": dict(CONNECTION_PREPARATION),
            "focusTrimMm": round(self.focus_trim_mm, 6),
            "sensorHome": {**self._sensor_home_state, "completed": list(self._sensor_home_state["completed"])},
            "alignmentRequired": self._alignment_required,
            "telemetryError": self._telemetry_error,
            "positionAgeS": round(time.monotonic() - self._telemetry_at, 3) if self._telemetry_at is not None else None,
            "manualMotion": {"active": self._manual_target_raw is not None,
                             "target": {n: self._local_of(n, raw) for n, raw in self._manual_target_raw.items()} if self._manual_target_raw else None,
                             "error": self._manual_error,
                             "stopping": self._manual_stop_deadline is not None},
            "localHome": dict(self.home_ref),
            "zMaxMm": self.z_max_mm,
        }

    def _disconnect_locked(self) -> None:
        self._poll_generation += 1
        if self.ser is not None:
            # Closing a communication session must not release a loaded
            # vertical stage. Motor power-off belongs to explicit E-STOP.
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.connected = False
        self._manual_target_raw = None
        self._manual_stop_deadline = None

    def _poll_loop(self, generation: int) -> None:
        """Background thread: refresh self.position from TP reads so status
        queries reflect current motion without blocking on move(). Exits
        when disconnect/estop increments the generation counter.

        Skips its own querying while a plan run (_run_worker) is active:
        that worker already TP-polls the exact axes it's moving to confirm
        arrival, so running both at once was hitting the ESP300 with two
        independent, uncoordinated streams of TP queries for the whole
        length of every "run on machine" job -- roughly doubling serial
        traffic for no benefit (self.position gets updated by _run_worker's
        own polling either way) and doubling the exposure window for
        whatever transient causes the occasional mid-run disconnect."""
        while True:
            for name, axis in JOG_AXES.items():
                with self._lock:
                    if self._poll_generation != generation or not self.connected or self.dry_run or self.ser is None:
                        return
                    if self._run_state["running"] or self._sensor_home_state["running"]:
                        continue
                    try:
                        raw = self._read_axis_position(axis)
                        self.raw_position[name] = raw
                        self.position[name] = self._local_of(name, raw)
                        self._telemetry_at = time.monotonic()
                    except RuntimeError as exc:
                        # The port itself died -- retrying every 5ms forever
                        # would otherwise spin silently with connected still
                        # showing True. Tear down the connection so status()
                        # reflects reality and a run in progress sees it.
                        self._telemetry_error = str(exc)
                        self._alignment_required = True
                        self._disconnect_locked()
                        return
                time.sleep(0.005)
            time.sleep(0.02)
            with self._lock:
                if self._manual_target_raw is not None and self.connected and generation == self._poll_generation:
                    self._check_manual_motion_locked()

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def connect(
        self,
        port: str,
        baudrate: int,
        dry_run: bool,
        *,
        expected_generation: int | None = None,
    ) -> dict:
        with self._lock:
            if expected_generation is not None and self._poll_generation != expected_generation:
                raise RuntimeError("Connection cancelled because the controller session changed. Press Connect again when ready.")
            self._require_no_sensor_home_locked()
            self._require_no_run_locked(allow_connection=True)
            self._require_manual_still_locked()
            if self.connected:
                if self.dry_run == bool(dry_run) and self.port == str(port or "COM5") and self.baudrate == int(baudrate or JOG_DEFAULT_BAUDRATE):
                    return {**self._status_locked(), "connectionKeptOpen": True}
                raise RuntimeError("Disconnect the idle session before changing port or connection mode.")
            if not dry_run and not AXIS_MAPPING_CONFIRMED:
                raise RuntimeError("Physical axis mapping is not confirmed. Hardware link test is available; live motor control is blocked.")
            self._disconnect_locked()
            self.dry_run = bool(dry_run)
            self.port = str(port or "COM5")
            self.baudrate = int(baudrate or JOG_DEFAULT_BAUDRATE)
            # Fresh connection: apply axis direction with offset 0 until
            # set_local_home() is explicitly called.
            # Only the explicit central-sensor search may redefine machine home.
            self.local_offset = {"x": 0.0, "y": 0.0, "z": 0.0}
            if not self.dry_run:
                try:
                    self.ser = open_esp300(self.port, self.baudrate)
                    for axis in JOG_AXES.values():
                        self._write(f"{axis}MO")
                        time.sleep(JOG_MOTOR_SETTLE_S)
                    for name, axis in JOG_AXES.items():
                        raw = self._read_axis_position(axis)
                        self.raw_position[name] = raw
                        self.position[name] = self._local_of(name, raw)
                except Exception:
                    # Release a failed COM/RFC2217 connection without sending
                    # additional motor commands (particularly on the Z axis).
                    if self.ser is not None:
                        try:
                            self.ser.close()
                        finally:
                            self.ser = None
                    raise
            else:
                session = next(iter(SESSIONS.values()), None)
                metadata = session["metadata"] if session else default_glass_metadata()
                x, y = metadata.get("usable_center_xy_mm") or (12.5, 12.5)
                self.position = {"x": float(x), "y": float(y), "z": 0.0}
                self.raw_position = {name: self._raw_of(name, value) for name, value in self.position.items()}
            self.home_ref = dict(self.position)
            self.z_home_raw = self.raw_position["z"]
            self.focus_trim_mm = 0.0
            self._alignment_required = not self.dry_run
            self._telemetry_error = None
            self._manual_error = None
            self._manual_stop_deadline = None
            self._telemetry_at = time.monotonic()
            self.connected = True
            self._poll_generation += 1
            generation = self._poll_generation
            if not self.dry_run:
                threading.Thread(target=self._poll_loop, args=(generation,), daemon=True).start()
            return self._status_locked()

    def probe_link(self, port: str, baudrate: int) -> dict:
        with self._lock:
            self._require_no_sensor_home_locked()
            if self._run_state["running"]:
                raise RuntimeError("Stop the current job before testing the hardware link.")
            if self.connected and not self.dry_run and self.ser is not None:
                if str(port) != self.port or int(baudrate) != self.baudrate:
                    raise RuntimeError("Test settings must match the current live connection.")
                return {"port": self.port, "baudrate": self.baudrate,
                        "versionReply": read_version(self.ser), "command": "VE",
                        "connectionKeptOpen": True}
            if self.ser is not None:
                raise RuntimeError("A previous serial session is still open. Close that session before testing.")
            return probe_version(str(port), int(baudrate))

    def disconnect(self) -> dict:
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            self._require_manual_still_locked()
            self._disconnect_locked()
            return self._status_locked()

    def move(self, axis_name: str, delta_mm: float, speed_mm_s: float) -> dict:
        if axis_name not in JOG_AXES:
            raise ValueError(f"Unknown jog axis {axis_name!r}.")
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            if self._manual_stop_deadline is not None:
                raise RuntimeError("Manual motion is stopping; wait for confirmed standstill.")
            if not self.connected:
                raise RuntimeError("Jog not connected. Connect first.")
            axis = JOG_AXES[axis_name]
            delta = float(delta_mm)
            if not math.isfinite(delta):
                raise ValueError("Jog distance must be finite.")
            speed = max(0.01, min(JOG_SPEED_MAX_MM_S, float(speed_mm_s)))

            if axis_name == "z":
                # Z jog is a live focus trim: it physically moves the stage
                # by delta, but folds that delta into local_offset["z"]
                # instead of self.position["z"]. Any focus/defocus target
                # already baked into the loaded plan is a fixed *local* Z
                # value, converted to a raw move via _raw_of() at the moment
                # it is sent (including by the "Run on machine" worker) -
                # so shifting the offset means every future scripted Z move
                # picks up this correction automatically instead of
                # snapping the stage back to the un-trimmed focus the next
                # time the plan touches Z. This is what lets the user
                # refocus mid-run without the correction being undone.
                new_raw = self.raw_position["z"] + delta
                check_z_target(new_raw, self.z_max_mm)
                if not self.dry_run:
                    self._write(f"{axis}VA{speed:.6f}")
                    time.sleep(0.02)
                    self._write(f"{axis}PA{new_raw:.6f}")
                if self.dry_run:
                    self.raw_position["z"] = new_raw
                else:
                    self._track_manual_target_locked({**(self._manual_target_raw or self.raw_position), "z": new_raw}, speed)
                self.local_offset["z"] += delta
                self.focus_trim_mm += delta
                return self._status_locked()

            target = dict(self.position)
            target[axis_name] = self.position[axis_name] + delta

            if not math.isfinite(target[axis_name]):
                raise ValueError("Jog target must be finite.")

            if not self.dry_run:
                self._write(f"{axis}VA{speed:.6f}")
                time.sleep(0.02)
                # PA (absolute move) is used in place of PR (relative move);
                # PR does not produce motion on this controller.
                self._write(f"{axis}PA{self._raw_of(axis_name, target[axis_name]):.6f}")
                # The command is issued without waiting for completion; the
                # background poll loop keeps self.position current from TP
                # reads for the duration of the move.
            if self.dry_run:
                self.raw_position[axis_name] = self._raw_of(axis_name, target[axis_name])
                self.position = target
            else:
                self._track_manual_target_locked({**(self._manual_target_raw or self.raw_position), axis_name: self._raw_of(axis_name, target[axis_name])}, speed)
            return self._status_locked()

    def estop(self) -> dict:
        from integrated_substrate import cancel_active
        cancel_active()
        self._run_stop.set()
        self._sensor_home_stop.set()
        with self._lock:
            if not self.dry_run and self.ser is not None:
                try:
                    self._write("AB")
                    # AB itself obeys the controller's ZE emergency settings.
                    # Omitting additional MF during homing does NOT guarantee
                    # holding power on vertical Y; load support must be verified.
                    if not self._sensor_home_state["running"]:
                        for axis in JOG_AXES.values():
                            self._write(f"{axis}MF")
                except Exception:
                    pass
            # Require an explicit reconnect after E-STOP before jogging resumes.
            self.connected = False
            self._poll_generation += 1
            self._manual_target_raw = None
            return self._status_locked()

    def diagnose(self) -> dict:
        """Read-only ESP300 status query. Sends no motion commands."""
        with self._lock:
            self._require_no_sensor_home_locked()
            if self.dry_run or self.ser is None:
                raise RuntimeError("Live connection required for diagnostics.")
            report = {}
            report["error_buffer"] = self._query("TB?")
            for name, axis in JOG_AXES.items():
                report[f"axis_{name}_motor_on"] = self._query(f"{axis}MO?")
                report[f"axis_{name}_motion_done"] = self._query(f"{axis}MD?")
                report[f"axis_{name}_axis_error"] = self._query(f"{axis}TE?")
                report[f"axis_{name}_stage_id"] = self._query(f"{axis}ID?")
                report[f"axis_{name}_raw_position"] = self._query(f"{axis}TP")
                report[f"axis_{name}_software_limits"] = self._query(f"{axis}ZS?")
                report[f"axis_{name}_hardware_limits"] = self._query(f"{axis}ZH?")
            return report

    def _send_absolute_locked(self, target: dict, speed: float) -> None:
        """Issue VA+PA for all three axes and return without waiting for
        arrival. Caller must hold self._lock. Confirmation of arrival is
        handled by the background poll loop."""
        self._require_no_sensor_home_locked()
        self._require_no_run_locked()
        self._require_manual_still_locked()
        if not all(math.isfinite(v) for v in target.values()):
            raise ValueError("XYZ target must be finite.")
        check_z_target(self._raw_of("z", target["z"]), self.z_max_mm)
        if not self.dry_run:
            for axis in JOG_AXES.values():
                self._write(f"{axis}VA{max(0.01, float(speed)):.6f}")
                time.sleep(0.02)
            for name, axis in JOG_AXES.items():
                raw = self._raw_of(name, target[name])
                self._write(f"{axis}PA{raw:.6f}")
            self._track_manual_target_locked({name: self._raw_of(name, value) for name, value in target.items()}, speed)
        else:
            for name in target:
                self.raw_position[name] = self._raw_of(name, target[name])
            self.position = dict(target)

    def home(self) -> dict:
        """Move to the local coordinate origin within the machine Z limit."""
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            self._require_manual_still_locked()
            if not self.connected:
                raise RuntimeError("Jog not connected. Connect first.")
            target = {"x": 0.0, "y": 0.0, "z": 0.0}
            # Use measured positions, not the optimistic target stored by a
            # previous command. A center search assigns drawing center at the
            # sensors, so Home immediately afterwards normally has no travel.
            if not self.dry_run:
                for name, axis in JOG_AXES.items():
                    raw = self._read_axis_position(axis)
                    self.raw_position[name] = raw
                    self.position[name] = self._local_of(name, raw)
            already_home = all(abs(self.position[name]) <= JOG_NOOP_TOLERANCE_MM for name in target)
            if already_home and not self.dry_run and any(self._query(f"{axis}MD?").strip() != "1" for axis in JOG_AXES.values()):
                raise RuntimeError("Stage is not confirmed stationary; wait before Home.")
            if not already_home:
                self._send_absolute_locked(target, JOG_HOME_SPEED_MM_S)
            # Home is only a move to local zero. It must not overwrite the
            # labeled return point, focus trim or coordinate frame.
            if already_home:
                self._manual_error = None
            return {**self._status_locked(), "alreadyHome": already_home,
                    "actionMessage": (
                        "Already at local (0, 0, 0); no move needed."
                        if already_home else "Home move commanded; watch the measured coordinates for arrival."
                    )}

    def set_local_home(self, x: float = 0.0, y: float = 0.0, z: float = 0.0) -> dict:
        """Assign local coordinates (x,y,z) to the current physical position
        without motion or any serial command. This adjusts only the
        software-side coordinate offset; the ESP300's absolute machine
        coordinate system is not modified. Passing the loaded design's
        center aligns reported and Run-on-machine coordinates with the
        design frame."""
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            self._require_manual_still_locked()
            if not self.connected:
                raise RuntimeError("Jog not connected. Connect first.")
            ref = {"x": float(x), "y": float(y), "z": float(z)}
            self._substrate_upper_right = None
            self.local_offset = {name: self.raw_position[name] - ESP300_AXIS_SIGNS[name] * ref[name] for name in ref}
            self.position = dict(ref)
            self.home_ref = dict(ref)
            self.z_home_raw = self.raw_position["z"]
            self.focus_trim_mm = 0.0
            self._alignment_required = False
            return self._status_locked()

    def go_to_local_home(self) -> dict:
        """Move X/Y/Z to the currently labeled local-home reference point
        (home_ref) - the position last marked via set_local_home(), e.g. the
        design center. Distinct from home(), which always targets literal
        local (0,0,0) regardless of what set_local_home() has labeled."""
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            self._require_manual_still_locked()
            if not self.connected:
                raise RuntimeError("Jog not connected. Connect first.")
            target = dict(self.home_ref)
            if not self.dry_run:
                for name, axis in JOG_AXES.items():
                    self.raw_position[name] = self._read_axis_position(axis)
                    self.position[name] = self._local_of(name, self.raw_position[name])
            already_home = all(abs(self.position[n] - value) <= JOG_NOOP_TOLERANCE_MM for n, value in target.items())
            if already_home:
                if not self.dry_run and any(self._query(f"{axis}MD?").strip() != "1" for axis in JOG_AXES.values()):
                    raise RuntimeError("Stage is not confirmed stationary; wait before returning to local home.")
                self._manual_error = None
                return {**self._status_locked(), "alreadyHome": True,
                        "actionMessage": "Already at the registered local home; no move needed."}
            self._send_absolute_locked(target, JOG_HOME_SPEED_MM_S)
            return self._status_locked()

    def goto(self, x: float, y: float, z: float) -> dict:
        """Move to a local XYZ target after conversion to the machine frame."""
        with self._lock:
            self._require_no_sensor_home_locked()
            if not self.connected:
                raise RuntimeError("Jog not connected. Connect first.")
            target = {"x": float(x), "y": float(y), "z": float(z)}
            self._send_absolute_locked(target, JOG_SPEED_MAX_MM_S)
            return self._status_locked()

    def save_ready_position(self, position) -> dict:
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            self._require_manual_still_locked()
            self.ready_position.save(position, 'manual-entry')
            return self._status_locked()

    def capture_ready_position(self, mode) -> dict:
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            self._require_manual_still_locked()
            if not self.connected or self.dry_run or mode != 'live':
                raise RuntimeError('현재 위치 저장은 Live 연결에서만 가능합니다.')
            measured = self._read_run_pose_locked()
            self.ready_position.save(measured, 'controller-readback')
            return self._status_locked()

    def move_to_saved_xy(self, mode) -> dict:
        return self.run_plan([], record_diagnostics=True, ready_settings={'axes': 'xy', 'mode': mode})

    def move_to_saved_z(self, mode) -> dict:
        return self.run_plan([], record_diagnostics=True, ready_settings={'axes': 'z', 'mode': mode})

    def move_to_saved_xyz(self, mode) -> dict:
        return self.run_plan([], record_diagnostics=True, ready_settings={'axes': 'xyz', 'mode': mode})

    def _check_ready_context_locked(self, segment):
        if (segment['readyContext'] != self._run_context_locked()
                or segment['readyAxisMap'] != (JOG_AXES, ESP300_AXIS_SIGNS)):
            raise RuntimeError('Ready coordinate configuration changed; stopping.')

    def run_plan(self, segments: list[dict], record_diagnostics: bool = False, *, point_settings: dict | None = None, line_settings: dict | None = None, circle_settings: dict | None = None, ready_settings: dict | None = None) -> dict:
        if isinstance(segments, dict) or any(isinstance(s, dict) and
                (s.get("schema") == "offline-depth-recipe-v1" or "target_relative_stage_z_mm" in s)
                for s in segments):
            raise RuntimeError("Offline depth recipes cannot be executed.")
        """Execute the given motion segments on the stage in order, with
        each segment's arrival confirmed before the next is issued. Runs in
        a background thread; poll run_status() for progress."""
        with self._lock:
            if any(s.get('readyMove') for s in segments):
                raise ValueError('Ready moves must be prepared by the Ready endpoint.')
            if sum(s is not None for s in (point_settings, line_settings, circle_settings, ready_settings)) > 1:
                raise ValueError("Choose one test recipe.")
            if ready_settings is not None:
                segments = prepare_ready_locked(self, ready_settings)
            if circle_settings is not None:
                from circle_test import prepare_circle_locked
                segments = prepare_circle_locked(self, circle_settings)
            if line_settings is not None:
                if point_settings is not None:
                    raise ValueError("Choose one test recipe.")
                from line_test import prepare_line_locked
                segments = prepare_line_locked(self, line_settings)
            if point_settings is not None:
                from point_test import prepare_point_locked
                segments = prepare_point_locked(self, point_settings)
            if CONNECTION_PREPARATION["active"]:
                raise RuntimeError("Connection preparation is in progress. Wait before running.")
            self._require_no_sensor_home_locked()
            self._require_manual_still_locked()
            if self._manual_error:
                raise RuntimeError(f"Previous manual move failed: {self._manual_error}")
            if self._alignment_required and point_settings is None and line_settings is None and circle_settings is None and ready_settings is None:
                from substrate_production import upper_right
                if not segments or not all(s.get('substrateTrial') for s in segments) or upper_right(self) is None:
                    raise RuntimeError("Sensor homing changed the machine reference. Align the sample and use Set local home (or Set upper-right for Substrate Test).")
            if not self.connected:
                raise RuntimeError("Jog not connected. Connect first.")
            if self._run_thread is not None and self._run_thread.is_alive():
                raise RuntimeError("A run is already in progress.")
            if not segments:
                raise RuntimeError("Nothing to run.")
            # Freeze targets in the server. Resume never accepts a client slice.
            saved = copy.deepcopy(segments)
            for segment in saved:
                to3 = segment.get("to3")
                if not isinstance(to3, (list, tuple)) or len(to3) != 3 or not all(math.isfinite(float(v)) for v in to3):
                    raise ValueError("Every segment needs a finite XYZ target.")
                if not math.isfinite(float(segment.get("duration", 0.1))) or float(segment.get("duration", 0.1)) <= 0:
                    raise ValueError("Segment duration must be positive and finite.")
                if segment.get("from3") is not None and (len(segment["from3"]) != 3 or not all(math.isfinite(float(v)) for v in segment["from3"])):
                    raise ValueError("Segment origin must contain finite XYZ coordinates.")
                if segment.get("speedMmS") is not None and (not math.isfinite(float(segment["speedMmS"])) or not 0 < float(segment["speedMmS"]) <= JOG_SPEED_MAX_MM_S):
                    raise ValueError(f"Segment speed must be within 0~{JOG_SPEED_MAX_MM_S} mm/s.")
                self._check_segment_z(segment)
            self._run_segments = saved
            self._run_origins = {}
            self._run_context = self._run_context_locked()
            self._run_pause_raw = None
            self._run_stop.clear()
            self._run_stop_sent = False
            self._run_stop_error = None
            self._run_state = {"running": True, "index": 0, "total": len(saved), "error": None, "done": False,
                               "jobId": uuid.uuid4().hex, "phase": "running", "activeSegment": 1,
                               "stopConfirmed": False, "resumable": False, "resumeBlockedReason": None}
            if ready_settings is not None:
                self._run_state['readyAxes'] = ready_settings['axes']
            # Explicit diagnostic runs only. No disk I/O or extra serial
            # queries in the execution loop; normal runs retain no trace.
            self._run_recording = record_diagnostics is True
            self._run_record_id = uuid.uuid4().hex if self._run_recording else None
            self._run_records = []
            self._run_started_at = time.monotonic()
            self._run_elapsed_final = None
            generation = self._poll_generation
            thread = threading.Thread(target=self._run_worker, args=(saved, generation, 0), daemon=True)
            self._run_thread = thread
            thread.start()
            return {**self._run_state, "diagnosticRunId": self._run_record_id}

    def run_snapshot(self) -> dict:
        with self._lock:
            index = self._run_state["index"]
            return {"run": dict(self._run_state), "remainingSegments": copy.deepcopy(self._run_segments[index:])}

    def _read_run_pose_locked(self, check_ready: bool = False) -> dict:
        """Strict status/position reads; MD=1 is required for *all* axes."""
        if self.dry_run:
            return dict(self.raw_position)
        if not self.connected or self.ser is None:
            raise RuntimeError("Controller connection is unavailable; standstill cannot be verified.")
        measured = {}
        for name, axis in JOG_AXES.items():
            reply = self._query(f"{axis}MD?").strip()
            if reply not in ("0", "1"):
                raise RuntimeError(f"Invalid motion-status reply for {name.upper()}: {reply!r}")
            if reply != "1":
                raise MotionNotStopped(f"{name.upper()} is still moving.")
            measured[name] = self._read_axis_position(axis)
            if check_ready and self._query(f"{axis}MO?").strip() != "1":
                raise RuntimeError(f"{name.upper()} motor is not enabled. Diagnose the fault before resuming.")
        if check_ready:
            reply = self._query("TE?").strip()
            if reply != "0":
                raise RuntimeError(f"ESP300 error {reply!r}. Diagnose the fault before resuming.")
        self.raw_position.update(measured)
        self.position = {name: self._local_of(name, raw) for name, raw in measured.items()}
        self._telemetry_at = time.monotonic()
        return measured

    def run_resume(self, job_id: str) -> dict:
        with self._lock:
            self._require_no_sensor_home_locked()
            self._require_no_run_locked()
            if not job_id or job_id != self._run_state.get("jobId"):
                raise RuntimeError("The saved job changed. Refresh the run state before resuming.")
            if not self._run_state.get("resumable") or self._run_state["index"] >= len(self._run_segments):
                raise RuntimeError(self._run_state.get("resumeBlockedReason") or "No confirmed stopped job to resume.")
            if not self.connected or self._alignment_required or self._run_context != self._run_context_locked():
                self._run_state.update(resumable=False, resumeBlockedReason="Connection or coordinate reference changed. Review alignment and start a new job.")
                raise RuntimeError(self._run_state["resumeBlockedReason"])
            measured = self._read_run_pose_locked(check_ready=True)
            if self._run_pause_raw is None or any(abs(measured[n] - self._run_pause_raw[n]) > 0.02 for n in measured):
                self._run_state.update(resumable=False, resumeBlockedReason="Stage position changed since the stop. Review the path and start a new job.")
                raise RuntimeError(self._run_state["resumeBlockedReason"])
            start = self._run_state["index"]
            for segment in self._run_segments[start:]:
                self._check_segment_z(segment)
            self._run_stop.clear()
            self._run_stop_sent = False
            self._run_stop_error = None
            self._run_state.update(running=True, phase="running", done=False, error=None, stopConfirmed=False,
                                   resumable=False, resumeBlockedReason=None, activeSegment=start + 1)
            self._record_run_event_locked("run_resume", firstSegment=start + 1, localPosition=dict(self.position))
            self._run_thread = threading.Thread(target=self._run_worker, args=(self._run_segments, self._poll_generation, start), daemon=True)
            self._run_thread.start()
            return dict(self._run_state)

    def _send_run_stop_locked(self) -> None:
        if not self._run_stop_sent:
            self._run_stop_sent = True
            self._record_run_event_locked("stop_command", command="ST", localPosition=dict(self.position))
            try:
                # ST uses normal deceleration and retains motor holding power.
                # AB invokes ZE emergency behavior and may switch power OFF.
                self._write("ST")
            except Exception as exc:
                self._run_stop_error = str(exc)

    def _confirm_run_stop(self, generation: int) -> dict:
        deadline = time.monotonic() + JOG_RUN_STOP_TIMEOUT_S
        while True:
            with self._lock:
                if generation != self._poll_generation or not self.connected:
                    raise RuntimeError("Connection changed; physical standstill is unconfirmed. Use the physical controller stop.")
                self._send_run_stop_locked()
                if self._run_stop_error:
                    raise RuntimeError(f"Stop command failed: {self._run_stop_error}. Physical standstill is unconfirmed.")
                try:
                    return self._read_run_pose_locked()
                except MotionNotStopped:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Stop timed out; physical standstill is unconfirmed. Use the physical controller stop.")
            time.sleep(0.02)

    def _record_run_event_locked(self, event: str, **details) -> None:
        if self._run_recording:
            self._run_records.append({
                "sequence": len(self._run_records) + 1,
                "timestampUtc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "elapsedS": round(time.monotonic() - self._run_started_at, 6),
                "event": event, **details,
            })

    def run_records(self, after: int = 0) -> dict:
        with self._lock:
            return {"diagnosticRunId": self._run_record_id,
                    "enabled": self._run_recording, "count": len(self._run_records),
                    "run": dict(self._run_state),
                    "records": self._run_records[max(0, after):]}

    def sensor_home(self, confirmed: bool = False) -> dict:
        """Reserve all motion, then search central sensors asynchronously.

        No connection is opened here. Live use requires explicit confirmation;
        connecting, loading a drawing and polling never start this operation.
        """
        with self._lock:
            if CONNECTION_PREPARATION["active"]:
                raise RuntimeError("Connection preparation is in progress. Wait before Center.")
            self._require_manual_still_locked()
            self._require_no_sensor_home_locked()
            if not self.connected or (not self.dry_run and self.ser is None):
                raise RuntimeError("Connect jog control first.")
            if self._run_state["running"]:
                raise RuntimeError("Stop the planned path before central sensor homing.")
            if not self.dry_run and confirmed is not True:
                raise RuntimeError("Confirm that the laser is off and all three axes have a clear path to their central sensors.")
            self._substrate_upper_right = None  # A new sensor search invalidates substrate registration immediately.
            self._sensor_home_state = {"running": True, "axis": None, "completed": [], "done": False, "error": None}
            self._sensor_home_stop.clear()
            generation = self._poll_generation
        thread = threading.Thread(target=self._sensor_home_worker, args=(generation,), daemon=True)
        self._sensor_home_thread = thread
        thread.start()
        return self.status()

    def _sensor_home_check_locked(self, generation: int) -> None:
        if self._sensor_home_stop.is_set() or generation != self._poll_generation or not self.connected:
            raise RuntimeError("Central sensor homing stopped. Reconnect and repeat the search before using the reference.")

    def _sensor_home_query(self, cmd: str, generation: int, *, hexadecimal: bool = False) -> float | int:
        with self._lock:
            self._sensor_home_check_locked(generation)
            reply = self._query(cmd).strip()
        if hexadecimal:
            if not re.fullmatch(r"[0-9A-Fa-f]+[Hh]?", reply):
                raise RuntimeError(f"Invalid controller reply to {cmd}: {reply!r}")
            return int(reply.rstrip("Hh"), 16)
        if not JOG_POSITION_PATTERN.fullmatch(reply) or not math.isfinite(float(reply)):
            raise RuntimeError(f"Invalid controller reply to {cmd}: {reply!r}")
        return float(reply)

    def _sensor_home_worker(self, generation: int) -> None:
        settings = {}
        changed = set()
        error = None
        motion_started = False
        try:
            if not self.dry_run:
                # Validate ALL axes before changing settings or starting any axis.
                if self._sensor_home_query("TE?", generation) != 0:
                    raise RuntimeError("Controller has a pending error. Diagnose it before homing.")
                for name, (model, mode) in SENSOR_HOME_AXES.items():
                    axis = JOG_AXES[name]
                    with self._lock:
                        self._sensor_home_check_locked(generation)
                        identity = self._query(f"{axis}ID?").split(",")[0].strip()
                    if identity.upper() != model.upper():
                        raise RuntimeError(f"Axis {name.upper()} expected {model}, got {identity!r}.")
                    for cmd, expected in (("SN?", 2), ("MO?", 1), ("MD?", 1)):
                        if self._sensor_home_query(f"{axis}{cmd}", generation) != expected:
                            raise RuntimeError(f"Axis {name.upper()} must use millimetres, have its motor enabled and be stationary ({cmd}).")
                    hardware_limits = self._sensor_home_query(f"{axis}ZH?", generation, hexadecimal=True)
                    software_limits = self._sensor_home_query(f"{axis}ZS?", generation, hexadecimal=True)
                    if hardware_limits & 5 != 5 or software_limits & 4 != 4:
                        raise RuntimeError(f"Axis {name.upper()} requires hardware limit checking and abort-on-limit protection. Settings were not changed.")
                    values = {cmd: self._sensor_home_query(f"{axis}{cmd}?", generation)
                              for cmd in ("OH", "OL", "OM", "SH", "SL", "SR")}
                    if not (0 < values["OL"] <= values["OH"] and values["SL"] < values["SH"] < values["SR"]):
                        raise RuntimeError(f"Axis {name.upper()} has invalid home speeds or home preset outside its software limits.")
                    current = self._sensor_home_query(f"{axis}TP", generation)
                    if not values["SL"] < current < values["SR"]:
                        raise RuntimeError(f"Axis {name.upper()} is outside its software limits; cannot prepare central homing.")
                    values["ZS"] = software_limits
                    settings[name] = values
                if self._sensor_home_query("TE?", generation) != 0:
                    raise RuntimeError("Controller rejected a preflight query. No homing command was sent.")

                # A real ESP300 may report ZS=4H (abort configured, checking
                # disabled). Only after ALL axes pass validation, enable bit 0.
                # Preserve every other bit and SL/SR; never weaken protection,
                # restore the disabled state, or save nonvolatile settings.
                for name, saved in settings.items():
                    if not saved["ZS"] & 1:
                        axis = JOG_AXES[name]
                        enabled = int(saved["ZS"]) | 1
                        with self._lock:
                            self._sensor_home_check_locked(generation)
                            self._write(f"{axis}ZS0{enabled:X}H")
                        actual = self._sensor_home_query(f"{axis}ZS?", generation, hexadecimal=True)
                        if actual != enabled:
                            raise RuntimeError(f"Axis {name.upper()} software limit checking could not be enabled; no homing command was sent.")
                if self._sensor_home_query("TE?", generation) != 0:
                    raise RuntimeError("Controller rejected software limit protection; no homing command was sent.")

            # Invalidate sample alignment as soon as a search may change machine
            # coordinates, including partially completed/aborted sequences.
            for name, (_, mode) in SENSOR_HOME_AXES.items():
                axis = JOG_AXES[name]
                with self._lock:
                    self._sensor_home_check_locked(generation)
                    self._sensor_home_state["axis"] = name
                    if not self.dry_run:
                        saved = settings[name]
                        high = min(saved["OH"], SENSOR_HOME_HIGH_MM_S)
                        low = min(saved["OL"], SENSOR_HOME_LOW_MM_S, high)
                        changed.add(name)
                        self._write(f"{axis}OL{low:.9g}")
                        self._write(f"{axis}OH{high:.9g}")
                if not self.dry_run and self._sensor_home_query("TE?", generation) != 0:
                    raise RuntimeError(f"Axis {name.upper()} home speed setup failed.")
                with self._lock:
                    self._sensor_home_check_locked(generation)
                    self._alignment_required = True
                    motion_started = True
                    if not self.dry_run:
                        self._write(f"{axis}OR{mode}")
                if not self.dry_run:
                    deadline = time.monotonic() + SENSOR_HOME_TIMEOUT_S
                    while True:
                        # MD is the documented status query during an OR search.
                        done = self._sensor_home_query(f"{axis}MD?", generation)
                        if done == 1:
                            break
                        if done != 0:
                            raise RuntimeError(f"Axis {name.upper()} returned invalid motion status.")
                        moving_raw = self._sensor_home_query(f"{axis}TP", generation)
                        with self._lock:
                            self._sensor_home_check_locked(generation)
                            self.raw_position[name] = moving_raw
                            self.position[name] = self._local_of(name, moving_raw)
                            self._telemetry_at = time.monotonic()
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f"Axis {name.upper()} central sensor search timed out.")
                        self._sensor_home_stop.wait(0.1)
                    if self._sensor_home_query("TE?", generation) != 0:
                        raise RuntimeError(f"Axis {name.upper()} central sensor search reported a controller error.")
                    raw = self._sensor_home_query(f"{axis}TP", generation)
                    if abs(raw - settings[name]["SH"]) > 0.01:
                        raise RuntimeError(f"Axis {name.upper()} did not reach its home preset.")
                else:
                    # Simulation never calls a serial method, even with a handle
                    # accidentally present. Each simulated sensor is at raw zero.
                    self._sensor_home_stop.wait(0.03)
                    raw = 0.0
                with self._lock:
                    self._sensor_home_check_locked(generation)
                    self.raw_position[name] = raw
                    self.position[name] = self._local_of(name, raw)
                    self._telemetry_at = time.monotonic()
                    self._sensor_home_state["completed"].append(name)
            with self._lock:
                self._sensor_home_check_locked(generation)
                # Sensor/raw origin and drawing origin are different frames.
                # Place the sensor center at the drawing center provisionally;
                # Set local home still confirms actual sample/focus alignment.
                cx, cy = glass_start_xy_from_metadata(default_glass_metadata())
                self.position = dict(x=cx, y=cy, z=0.0)
                self.local_offset = {name: self.raw_position[name] - ESP300_AXIS_SIGNS[name] * value
                                     for name, value in self.position.items()}
                self.home_ref = dict(self.position)
                self.z_home_raw = self.raw_position["z"]
                self.focus_trim_mm = 0.0
        except Exception as exc:
            error = str(exc)
            with self._lock:
                if generation == self._poll_generation and self.ser is not None and not self.dry_run and motion_started:
                    try:
                        self._write("AB")  # Firmware ZE settings determine emergency-stop motor power.
                    except Exception as abort_error:
                        error += f" Abort could not be sent ({abort_error}); use the physical controller stop."
                    self.connected = False  # no further jog/plan on uncertain coordinates
                    self._poll_generation += 1
        finally:
            # Restore only after a completed search (or pre-motion failure).
            # After an abort the controller may still be stopping; send no setup
            # commands then. Reduced speeds/mode may remain until reviewed.
            with self._lock:
                if not self.dry_run and self.ser is not None and generation == self._poll_generation and (not error or not motion_started):
                    try:
                        for name in changed:
                            axis, saved = JOG_AXES[name], settings[name]
                            for cmd in ("OH", "OL", "OM"):
                                self._write(f"{axis}{cmd}{saved[cmd]:.9g}")
                        if changed and self._query("TE?").strip() != "0":
                            raise RuntimeError("Controller rejected restored home settings.")
                    except Exception as exc:
                        error = f"{error or 'Central search finished'}. Home settings restore failed: {exc}"
                        self.connected = False
                        self._poll_generation += 1
                self._sensor_home_state.update(running=False, axis=None, done=error is None, error=error)

    def _fault_context(self) -> str:
        """Best-effort ESP300 error-buffer/axis-error snapshot to attach to
        a failure message -- never raises itself (diagnostics failing
        shouldn't hide the original failure), and never called while
        self._lock is held (diagnose() takes it itself)."""
        if self.dry_run or self.ser is None:
            return ""
        try:
            report = self.diagnose()
        except Exception:
            return ""
        parts = []
        err_buf = report.get("error_buffer", "")
        if err_buf and not err_buf.startswith("0,") and err_buf != "0":
            parts.append(f"controller error buffer: {err_buf}")
        for name in JOG_AXES:
            code = report.get(f"axis_{name}_axis_error", "")
            if code and code != "0":
                parts.append(f"{name} axis error {code}")
        return f" ESP300 reports: {'; '.join(parts)}." if parts else ""

    def _run_worker(self, segments: list[dict], generation: int, start_index: int = 0) -> None:
        error = None
        stopped = False
        current_segment = start_index + 1
        try:
            tolerance = 0.02
            for index in range(start_index, len(segments)):
                segment = segments[index]
                tolerance = .001 if segment.get('readyMove') else .02
                current_segment = index + 1
                duration = max(float(segment.get("duration", 0.1)), 0.05)
                target = dict(zip(("x", "y", "z"), map(float, segment["to3"])))
                axes_to_move = []
                if segment.get("substrateTrial") and segment.get("dwellSeconds") is not None:
                    dwell=float(segment["dwellSeconds"])
                    if not math.isfinite(dwell) or dwell != 3.0:raise RuntimeError("Invalid substrate dwell")
                    app_audit.emit("substrate_dwell_start", seconds=dwell, segment=current_segment)
                    deadline=time.monotonic()+dwell
                    while True:
                        with self._lock:
                            if self._run_stop.is_set():raise RunStopRequested()
                            if not self.connected or generation != self._poll_generation or segment.get("substrateContext") != self._run_context_locked() or segment.get("substrateAxes") != (JOG_AXES,ESP300_AXIS_SIGNS):
                                raise RuntimeError("Substrate reference changed during dwell")
                            self._run_state["activeSegment"]=current_segment
                            app_audit.RECORDER.checkpoint()
                        remaining=deadline-time.monotonic()
                        if remaining<=0:break
                        self._run_stop.wait(min(.05,remaining))
                    with self._lock:
                        if self._run_stop.is_set():raise RunStopRequested()
                        self._run_state["index"]=current_segment
                    app_audit.emit("substrate_dwell_complete", seconds=dwell, segment=current_segment)
                    continue
                with self._lock:
                    if self._run_stop.is_set():
                        raise RunStopRequested()
                    if self._poll_generation != generation or not self.connected:
                        raise RuntimeError("Stage connection changed during the job.")
                    if segment.get('readyMove'):
                        self._check_ready_context_locked(segment)
                    if segment.get("pointTest"):
                        if segment.get("pointContext") != self._run_context_locked() or segment.get("pointAxes") != (JOG_AXES, ESP300_AXIS_SIGNS):
                            raise RuntimeError("Point test coordinate configuration changed; stopping")
                    if segment.get("lineTest"):
                        if segment.get("lineContext") != self._run_context_locked() or segment.get("lineAxes") != (JOG_AXES, ESP300_AXIS_SIGNS):
                            raise RuntimeError("Line test coordinate configuration changed; stopping")
                    if segment.get("circleTest"):
                        if segment.get("circleContext") != self._run_context_locked() or segment.get("circleAxes") != (JOG_AXES, ESP300_AXIS_SIGNS):
                            raise RuntimeError("Circle test coordinate configuration changed; stopping")
                    if segment.get("substrateTrial"):
                        if segment.get("substrateContext") != self._run_context_locked() or segment.get("substrateAxes") != (JOG_AXES, ESP300_AXIS_SIGNS):
                            raise RuntimeError("Substrate origin/configuration changed; stopping")
                        app_audit.RECORDER.checkpoint()
                    self._run_state["activeSegment"] = current_segment
                    cur = dict(self.position)
                    planned_origin = dict(zip(("x", "y", "z"), map(float, segment["from3"]))) if segment.get("from3") else dict(cur)
                    origin = self._run_origins.setdefault(index, planned_origin)
                    self._record_run_event_locked(
                        "segment_start", segment=current_segment, kind=segment.get("kind"),
                        pathIndex=segment.get("pathIndex"), layer=segment.get("layer"),
                        targetLocal=dict(target),
                        targetRaw={name: self._raw_of(name, value) for name, value in target.items()},
                        plannedDurationS=duration, dryRun=self.dry_run,
                    )
                    names = self._segment_axes(segment)
                    self._check_segment_z(segment)
                    planned_distance = math.sqrt(sum((target[n] - origin[n]) ** 2 for n in names))
                    remaining_distance = math.sqrt(sum((target[n] - cur[n]) ** 2 for n in names))
                    path_speed = float(segment.get("speedMmS", planned_distance / duration))
                    if remaining_distance > 1e-6 and path_speed <= 0:
                        raise RuntimeError("An initial positioning segment needs an explicit positive travel speed.")
                    effective_duration = remaining_distance / path_speed if path_speed > 0 else duration
                    for name in names:
                        if segment.get('readyMove'):
                            self._check_ready_context_locked(segment)
                        if abs(target[name] - cur[name]) <= 1e-6:
                            continue
                        axis = JOG_AXES[name]
                        # Keep the configured vector speed even when a repeat
                        # starts at the previous job's endpoint. Reusing the
                        # center-based duration with that longer first travel
                        # used to accelerate it up to the axis speed cap.
                        speed = max(0.01, min(JOG_SPEED_MAX_MM_S, path_speed * abs(target[name] - cur[name]) / remaining_distance))
                        if self._run_stop.is_set():
                            raise RunStopRequested()
                        self._write(f"{axis}VA{speed:.6f}")
                        time.sleep(0.02)
                        if self._run_stop.is_set():
                            raise RunStopRequested()
                        raw = segment["readyRaw"][name] if segment.get("readyMove") else self._raw_of(name, target[name])
                        self._write(f"{axis}PA{raw:.6f}")
                        axes_to_move.append((name, axis, raw))
                    # Never assign targets to measured position in live mode.

                if self.dry_run:
                    time.sleep(min(duration, 0.03))
                    with self._lock:
                        if self._run_stop.is_set():
                            raise RunStopRequested()
                        for name in names:
                            self.position[name] = target[name]
                            self.raw_position[name] = segment["readyRaw"][name] if segment.get("readyMove") else self._raw_of(name, target[name])
                else:
                    deadline = time.monotonic() + max(3.0, effective_duration * 4 + 2.0)
                    while True:
                        if self._run_stop.is_set():
                            raise RunStopRequested()
                        if segment.get('readyMove'):
                            with self._lock:
                                self._check_ready_context_locked(segment)
                        if segment.get("pointTest"):
                            if segment.get("pointContext") != self._run_context_locked() or segment.get("pointAxes") != (JOG_AXES, ESP300_AXIS_SIGNS):
                                raise RuntimeError("Point test coordinate configuration changed while moving")
                        if segment.get("lineTest"):
                            if segment.get("lineContext") != self._run_context_locked() or segment.get("lineAxes") != (JOG_AXES, ESP300_AXIS_SIGNS):
                                raise RuntimeError("Line test coordinate configuration changed while moving")
                        if segment.get("circleTest"):
                            if segment.get("circleContext") != self._run_context_locked() or segment.get("circleAxes") != (JOG_AXES, ESP300_AXIS_SIGNS):
                                raise RuntimeError("Circle test coordinate configuration changed while moving")
                        if segment.get("substrateTrial"):
                            app_audit.RECORDER.checkpoint()
                            if segment.get("substrateContext") != self._run_context_locked() or segment.get("substrateAxes") != (JOG_AXES, ESP300_AXIS_SIGNS):
                                raise RuntimeError("Substrate reference changed while moving")
                        arrived = True
                        for name, axis, target_raw in axes_to_move:
                            # Release the serial lock between axes. A stop must
                            # not wait through every axis's full retry budget.
                            with self._lock:
                                if self._run_stop.is_set():
                                    raise RunStopRequested()
                                if generation != self._poll_generation or not self.connected:
                                    raise RuntimeError("Stage connection changed during the job.")
                                actual = self._read_axis_position(axis, interrupt_on_stop=True)
                                self.raw_position[name] = actual
                                self.position[name] = self._local_of(name, actual)
                                self._telemetry_at = time.monotonic()
                                if abs(actual - target_raw) > tolerance:
                                    arrived = False
                                else:
                                    md = self._query(f"{axis}MD?").strip()
                                    if md not in ("0", "1"):
                                        raise RuntimeError(f"Invalid {name.upper()} motion status: {md!r}")
                                    arrived = arrived and md == "1"
                        # A stationary axis can still be settling after the
                        # preceding segment. Its last TP must not remain on
                        # screen for an entire long XY cut (notably focus Z).
                        if time.monotonic() - self._run_passive_at >= JOG_RUN_PASSIVE_POLL_S:
                            moved = {name for name, _, _ in axes_to_move}
                            for name, axis in JOG_AXES.items():
                                if name in moved:
                                    continue
                                with self._lock:
                                    if self._run_stop.is_set():
                                        raise RunStopRequested()
                                    actual = self._read_axis_position(axis, interrupt_on_stop=True)
                                    self.raw_position[name] = actual
                                    self.position[name] = self._local_of(name, actual)
                                    self._telemetry_at = time.monotonic()
                            self._run_passive_at = time.monotonic()
                        if arrived:
                            break
                        if time.monotonic() >= deadline:
                            raise RuntimeError(f"Segment {current_segment}/{len(segments)} timed out waiting for arrival.")
                        self._run_stop.wait(0.02)

                with self._lock:
                    if self._run_stop.is_set():
                        raise RunStopRequested()
                    # Only verified complete segments advance the resume index.
                    if segment.get('readyMove'):
                        self._check_ready_context_locked(segment)
                        measured = self._read_run_pose_locked()
                        if any(abs(measured[n] - segment['readyRaw'][n]) > tolerance for n in 'xyz'):
                            raise RuntimeError('Ready final position differs from the measured target.')
                    self._run_state["index"] = current_segment
                    self._record_run_event_locked(
                        "segment_complete", segment=current_segment, kind=segment.get("kind"),
                        targetLocal=dict(target), localPosition=dict(self.position),
                        measuredRaw={name: self.raw_position[name] for name, _, _ in axes_to_move},
                        arrivalToleranceMm=tolerance, dryRun=self.dry_run,
                    )
        except RunStopRequested:
            stopped = True
        except Exception as exc:
            error = str(exc)
            with self._lock:
                self._record_run_event_locked("segment_error", segment=current_segment, error=error,
                                              localPosition=dict(self.position))
        finally:
            # Keep running=True until standstill is actually confirmed. A
            # fault also stops the outstanding PA; ending a Python loop alone
            # cannot stop a command already being executed by the ESP300.
            if stopped or error or self._run_stop.is_set():
                stopped = stopped or self._run_stop.is_set()
                with self._lock:
                    self._run_state.update(phase="stopping", resumable=False)
                try:
                    measured = self._confirm_run_stop(generation)
                    with self._lock:
                        self._run_pause_raw = dict(measured)
                        self._run_state["stopConfirmed"] = True
                        resumable = (self.connected and not self._alignment_required
                                     and self._run_context == self._run_context_locked()
                                     and self._run_state["index"] < len(segments))
                        self._run_state.update(resumable=resumable,
                            resumeBlockedReason=None if resumable else "The job is complete or its coordinate reference changed.")
                        self._record_run_event_locked("stop_confirmed", segment=current_segment,
                            completedSegments=self._run_state["index"], measuredRaw=dict(measured),
                            localPosition=dict(self.position))
                except Exception as stop_error:
                    error = f"{error + ' ' if error else ''}{stop_error}"
                    with self._lock:
                        self._run_state.update(stopConfirmed=False, resumable=False, resumeBlockedReason=str(stop_error))
                        # Do not send MF or auto-reconnect when stop status is
                        # unknown, especially with a vertical loaded axis.
                        self.connected = False
                        self._poll_generation += 1
                        self._record_run_event_locked("stop_unconfirmed", error=str(stop_error))
                with self._lock:
                    if stopped:
                        self._record_run_event_locked("segment_stopped", segment=current_segment,
                            completedSegments=self._run_state["index"], localPosition=dict(self.position))
            with self._lock:
                done = not stopped and not error
                if done:
                    self._run_elapsed_final = time.monotonic() - self._run_started_at
                self._run_state.update(running=False, done=done, error=error or ("Stopped." if stopped else None),
                    phase="completed" if done else ("failed" if error else "stopped"),
                    activeSegment=None)
                self._record_run_event_locked("run_end", **dict(self._run_state))

    def current_raw_z(self, refresh: bool = False) -> float:
        with self._lock:
            if refresh and self.connected and not self.dry_run:
                self.raw_position["z"] = self._read_axis_position(JOG_AXES["z"])
                self.position["z"] = self._local_of("z", self.raw_position["z"])
            return self.raw_position["z"]

    def run_status(self) -> dict:
        with self._lock:
            elapsed = (self._run_elapsed_final if self._run_elapsed_final is not None else time.monotonic() - self._run_started_at)
            return {**self._run_state, "elapsedS": round(elapsed, 3) if self._run_state.get("jobId") else None}

    def run_stop(self) -> dict:
        from integrated_substrate import cancel_active
        cancel_active()
        # Set before acquiring the serial lock so the worker cannot send the
        # next PA while the stop request is waiting behind a TP query.
        if self._run_state["running"]:
            self._run_stop.set()
        with self._lock:
            if self._run_state["running"]:
                self._run_state.update(phase="stopping", resumable=False)
                self._record_run_event_locked("stop_requested", completedSegments=self._run_state["index"])
                self._send_run_stop_locked()
            return dict(self._run_state)


JOG = JogController()


CAMERA_STREAM_FPS = 20
# ponytail: 2026-09-10, first attempt -- 15->30 crashed the whole process under real
# scan load (no traceback). 2026-09-10, second attempt -- retrying at a smaller step (20,
# not 30) and isolating the variable: verify idle stability alone first, THEN add scan
# load, instead of changing both at once like last time. If 20 also wedges under scan
# load, the ceiling is below the loop's own per-frame cost (~26fps observed max throughput
# at fps=30, i.e. it was already CPU-bound, not sleep-bound) and the real fix is what the
# first attempt's note said: decouple cap.read() (cheap, drains the USB buffer) from
# JPEG-encode + blob-detect (expensive, can stay at 15) instead of raising both together.
CAMERA_JPEG_QUALITY = 80
CAMERA_BOUNDARY = "focusframe"

# Red-spot tracking: HSV mask (hue wraps at 0/180, so two ranges) plus a
# high-value gate so a dim red surface doesn't get picked up as "the spot".
RED_HUE_LOW = ((0, 90, 120), (10, 255, 255))
RED_HUE_HIGH = ((170, 90, 120), (180, 255, 255))
# A genuinely overexposed flash core clips toward white -- low saturation,
# high value -- so it falls OUTSIDE the red hue mask above. This second,
# hue-independent mask catches that core; scattered light shows up as many
# small blobs across both masks, so tracking is done on the whole set
# rather than trusting whichever single blob happens to be largest.
CORE_MIN_GRAY = 250
BRIGHT_SPOT_MIN_AREA_PX = 4
MAX_TRACKED_BLOBS = 8
# ponytail: both eyeballed, not measured against real spike frames yet --
# re-tune using the -1.0~-0.5mm / +0.3mm spike-region rescan (2026-09-11 plan).
MAX_PRIOR_JUMP_PX = 40  # nearest prior-frame match farther than this is untrusted
MIN_CANDIDATE_AREA_PX = 16  # red blobs smaller than this are noise, not a candidate target


def _nearest_within_gate(items, prior_xy, max_jump_px, xy_of):
    """Pick the item whose (x, y) is nearest prior_xy, but only if that
    nearest pick is within max_jump_px -- a real target moves smoothly frame
    to frame, so the nearest candidate landing farther than this is more
    likely a stray reflection than the same target's next position. Returns
    None when nothing is within the gate (caller falls back to area-based
    selection instead of locking onto a spurious jump).
    """
    px, py = prior_xy
    best = min(items, key=lambda it: (xy_of(it)[0] - px) ** 2 + (xy_of(it)[1] - py) ** 2)
    bx, by = xy_of(best)
    if (bx - px) ** 2 + (by - py) ** 2 > max_jump_px ** 2:
        return None
    return best


def _predict_xy(prior_xy: tuple[float, float] | None, velocity_xy: tuple[float, float]) -> tuple[float, float] | None:
    """Where the tracked spot should be *this* frame, given where it was
    last frame and how fast it's been moving -- a straight-line stage move
    keeps a roughly constant on-screen velocity, so prior + velocity is a
    tighter gate anchor than a static prior alone (which always lags one
    frame behind on anything actually moving)."""
    if prior_xy is None:
        return None
    return (prior_xy[0] + velocity_xy[0], prior_xy[1] + velocity_xy[1])


def _update_velocity_xy(
    prior_xy: tuple[float, float] | None, velocity_xy: tuple[float, float], new_xy: tuple[float, float]
) -> tuple[float, float]:
    """Smoothed frame-to-frame velocity update, called after a real
    detection lands. Folds in the latest (possibly noisy) displacement at
    half weight rather than replacing the estimate outright, so one jittery
    frame can't itself swing next frame's prediction wildly."""
    if prior_xy is None:
        return (0.0, 0.0)
    raw = (new_xy[0] - prior_xy[0], new_xy[1] - prior_xy[1])
    return (0.5 * velocity_xy[0] + 0.5 * raw[0], 0.5 * velocity_xy[1] + 0.5 * raw[1])


def locate_bright_regions(frame: np.ndarray, prior_xy: tuple[float, float] | None = None) -> dict:
    """Track every bright blob (red glow + overexposed core) in `frame`,
    but score/locate only the ONE real target among them.

    A genuine in-focus flash is a red-glow blob (green circle in the
    camera-panel overlay) with a saturated white core (yellow circle)
    nested inside it. Everything else -- stray reflections, other hot
    spots that never saturate -- is noise and used to happen to still
    count toward `score`/`x`/`y` just by being in frame, which could drag
    the autofocus metric toward a reflection instead of the actual spot.
    So: find the largest red blob that contains a core blob's centroid,
    and derive score/x/y from ONLY that pair's mask. If no red blob has a
    nested core yet (mid-scan, off focus, nothing saturated), fall back to
    the best red-glow blob alone (see below) instead of dropping straight
    to 0 -- only a frame with no red glow at all scores exactly 0.

    Among multiple red blobs that each have a nested core (e.g. a stray
    reflection happens to saturate too), the stage only moves smoothly --
    the real spot's pixel position from one frame to the next doesn't
    teleport -- so `prior_xy` (the previous frame's chosen target position,
    in this same frame's local coordinates) breaks the tie by proximity
    instead of by whichever blob happens to be biggest that frame. Pass
    None when there's no established anchor yet (first frame, just
    reconnected, ROI just changed).

    Returns {"blobs": [...], "score", "x", "y", "n_blobs"}. `blobs` still
    lists every tracked candidate (for the panel overlay); "n_blobs" is
    the count of all of them, not just the chosen target. Coordinates are
    in pixel coordinates of `frame` as given (caller adds any ROI offset).
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    value = hsv[:, :, 2]

    red_mask = cv2.inRange(hsv, *RED_HUE_LOW) | cv2.inRange(hsv, *RED_HUE_HIGH)
    core_mask = np.where(gray >= CORE_MIN_GRAY, 255, 0).astype(np.uint8)

    def find_entries(kind: str, mask: np.ndarray) -> list[dict]:
        entries = []
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in contours:
            area = cv2.contourArea(c)
            if area < BRIGHT_SPOT_MIN_AREA_PX:
                continue
            moments = cv2.moments(c)
            if moments["m00"] <= 0:
                continue
            blob_mask = np.zeros(mask.shape, dtype=np.uint8)
            cv2.drawContours(blob_mask, [c], -1, 255, -1)
            entries.append(
                {
                    "kind": kind,
                    "x": float(moments["m10"] / moments["m00"]),
                    "y": float(moments["m01"] / moments["m00"]),
                    "area": float(area),
                    "brightness": float(np.max(value[blob_mask > 0])),
                    "contour": c,
                    "mask": blob_mask,
                }
            )
        return entries

    red_entries = find_entries("red", red_mask)
    core_entries = find_entries("core", core_mask)
    all_entries = red_entries + core_entries

    if not all_entries:
        return {"blobs": [], "score": 0.0, "x": None, "y": None, "n_blobs": 0}

    # Noise-area gate: a red blob this small is more likely sensor speckle than
    # a real glow, so it's excluded before it can ever become the chosen
    # target (it still shows up in the overlay via all_entries/blobs below).
    # Falls back to the unfiltered list if gating would leave nothing at all.
    sizeable_red = [r for r in red_entries if r["area"] >= MIN_CANDIDATE_AREA_PX] or red_entries

    candidates = []  # (red_entry, core_entry) pairs where the core sits inside the red blob
    for r in sizeable_red:
        for co in core_entries:
            if cv2.pointPolygonTest(r["contour"], (co["x"], co["y"]), False) >= 0:
                candidates.append((r, co))
                break

    target_red = None
    target_core = None
    if candidates:
        if prior_xy is not None:
            nearest = _nearest_within_gate(candidates, prior_xy, MAX_PRIOR_JUMP_PX, lambda rc: (rc[0]["x"], rc[0]["y"]))
            target_red, target_core = nearest if nearest is not None else max(candidates, key=lambda rc: rc[0]["area"])
        else:
            target_red, target_core = max(candidates, key=lambda rc: rc[0]["area"])

    if target_red is not None:
        target_mask = cv2.bitwise_or(target_red["mask"], target_core["mask"])
        moments = cv2.moments(target_mask, binaryImage=True)
        score = float(np.sum(value[target_mask > 0]))
        wx = moments["m10"] / moments["m00"] if moments["m00"] > 0 else None
        wy = moments["m01"] / moments["m00"] if moments["m00"] > 0 else None
    elif sizeable_red:
        # No red blob has a saturated core yet -- genuinely off-focus, not a
        # dropped frame. The old behavior scored this 0.0, same as "nothing
        # lit up at all"; across a scan that meant the metric fell off a
        # cliff the moment the core stopped saturating, then jumped straight
        # back up once it did, instead of the glow's own brightness rising
        # and falling smoothly through that whole stretch. Score the best
        # red-glow blob alone (no core requirement) here instead, so the
        # curve tapers off through the actually-dimmer region rather than
        # snapping to 0 -- still always less than a paired red+core score
        # for the same glow, since that also sums the saturated core pixels
        # on top of it, so this can't make a near-focus read look bigger
        # than a true in-focus one.
        nearest = _nearest_within_gate(sizeable_red, prior_xy, MAX_PRIOR_JUMP_PX, lambda r: (r["x"], r["y"])) if prior_xy is not None else None
        target_red = nearest if nearest is not None else max(sizeable_red, key=lambda r: r["area"])
        moments = cv2.moments(target_red["mask"], binaryImage=True)
        score = float(np.sum(value[target_red["mask"] > 0]))
        wx = moments["m10"] / moments["m00"] if moments["m00"] > 0 else None
        wy = moments["m01"] / moments["m00"] if moments["m00"] > 0 else None
    else:
        score = 0.0
        wx = wy = None

    all_entries.sort(key=lambda b: b["area"], reverse=True)
    blobs = [{k: v for k, v in b.items() if k not in ("contour", "mask")} for b in all_entries[:MAX_TRACKED_BLOBS]]

    return {
        "blobs": blobs,
        "score": score,
        "x": wx,
        "y": wy,
        "n_blobs": len(all_entries),
    }


class CameraController:
    """Background UVC capture for the live focus-brightness preview.

    A single capture thread keeps grabbing frames while connected, so the
    MJPEG stream endpoint and the brightness status endpoint both just read
    the latest already-decoded frame instead of contending for the device.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.cap: cv2.VideoCapture | None = None
        self.index: int | None = None
        self.connected = False
        self.error: str | None = None
        self.roi: tuple[int, int, int, int] | None = None
        self._latest_jpeg: bytes | None = None
        self._latest_stats = {"mean": None, "max": None}
        self._latest_regions: dict | None = None
        self._latest_frame_time = 0.0  # time.monotonic() when _latest_stats/_regions were last written
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Previous frame's chosen target position, in region-local (pre-ROI-offset)
        # pixel coords. Updated only from _capture_loop's own thread each frame;
        # other threads only ever reset it to None (on reconnect/ROI change), so
        # skipping the lock here just risks one stale-anchor frame at worst, never
        # a real race.
        self._prior_target_xy: tuple[float, float] | None = None
        # Frame-to-frame velocity of _prior_target_xy (pixels/frame), smoothed.
        # The stage moves in a straight line at roughly constant speed, so the
        # real spot's next position is prior + velocity, not just prior (a
        # static anchor) -- extrapolating tightens the prior_xy gate against
        # a stray reflection that happens to be merely close to last frame's
        # spot instead of on the same line of motion. Reset alongside
        # _prior_target_xy any time that anchor is invalidated/reset.
        self._prior_velocity_xy: tuple[float, float] = (0.0, 0.0)
        # Frozen-frame watchdog: cap.read() can keep returning ok=True with a
        # driver-cached/duplicate frame forever (a real UVC/USB quirk, not
        # covered by the grabFrame-failure counter below since ok is True) --
        # seen live on this rig as a "focus scan" that kept moving Z for 20+
        # minutes while the reported score sat pinned at one exact value the
        # whole time, because _latest_frame_time still advances on every loop
        # tick even though the pixel content never changed. (mean, max) being
        # bit-identical across many consecutive real frames is not something
        # sensor noise produces by chance, so it's used here as a cheap stand-in
        # for a full frame-content hash.
        self._last_stats_signature: tuple[float, float] | None = None
        self._frozen_frame_count = 0

    def connect(self, index: int, backend: int = cv2.CAP_MSMF) -> dict:
        with self._lock:
            self._disconnect_locked()
            cap = cv2.VideoCapture(int(index), backend)
            if not cap.isOpened():
                cap.release()
                self.error = f"Camera index {index} did not open."
                raise RuntimeError(self.error)
            # Virtual devices can open successfully but never provide video.
            # Verify capture before reporting a successful connection.
            deadline = time.monotonic() + 3.0
            while True:
                ok, frame = cap.read()
                if ok and frame is not None and frame.size > 0:
                    break
                if time.monotonic() >= deadline:
                    cap.release()
                    self.error = (
                        f"Camera index {index} opened but produced no video frames. "
                        "Select the physical UVC camera's index instead of a virtual camera."
                    )
                    raise RuntimeError(self.error)
                time.sleep(0.05)
            self.cap = cap
            self.index = int(index)
            self.connected = True
            self._stop.clear()
            thread = threading.Thread(target=self._capture_loop, daemon=True)
            self._thread = thread
            thread.start()
            return self._status_locked()

    def _disconnect_locked(self, error: str | None = None) -> None:
        self._stop.set()
        if self.cap is not None:
            self.cap.release()
        self.cap = None
        self.connected = False
        self.error = error
        self._latest_jpeg = None
        self._latest_stats = {"mean": None, "max": None}
        self._latest_regions = None
        self._latest_frame_time = 0.0
        self._prior_target_xy = None
        self._prior_velocity_xy = (0.0, 0.0)
        self._last_stats_signature = None
        self._frozen_frame_count = 0

    def disconnect(self) -> dict:
        with self._lock:
            self._disconnect_locked()
            return self._status_locked()

    def set_roi(self, roi: tuple[int, int, int, int] | None) -> dict:
        with self._lock:
            self.roi = roi
            self._prior_target_xy = None  # old anchor was in the previous ROI's local frame
            self._prior_velocity_xy = (0.0, 0.0)
            return self._status_locked()

    def select_target(self, x: float, y: float) -> dict:
        """User clicked a point on the camera stream (full-frame pixel
        coords, same as the blob overlay circles) to say "that one" among
        several red+core candidates. Store it as the tracking anchor --
        _capture_loop's continuity match then locks onto whichever
        candidate lands nearest this point, and keeps following it frame
        to frame from there."""
        with self._lock:
            roi = self.roi
            offset_x, offset_y = (roi[0], roi[1]) if roi is not None else (0, 0)
            self._prior_target_xy = (x - offset_x, y - offset_y)
            self._prior_velocity_xy = (0.0, 0.0)  # fresh manual pick, no motion history yet
            return self._status_locked()

    def _capture_loop(self) -> None:
        interval = 1.0 / CAMERA_STREAM_FPS
        consecutive_failures = 0
        max_consecutive_failures = CAMERA_STREAM_FPS * 5  # ~5s of dead reads
        while not self._stop.is_set():
            started = time.monotonic()
            with self._lock:
                cap = self.cap
            if cap is None:
                break
            ok, frame = cap.read()
            if ok and frame is not None:
                consecutive_failures = 0
                with self._lock:
                    roi = self.roi
                region = frame
                if roi is not None:
                    x, y, w, h = roi
                    cropped = frame[max(0, y) : y + h, max(0, x) : x + w]
                    if cropped.size > 0:
                        region = cropped
                gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
                stats = {"mean": float(np.mean(gray)), "max": float(np.max(gray))}

                signature = (stats["mean"], stats["max"])
                if signature == self._last_stats_signature:
                    self._frozen_frame_count += 1
                else:
                    self._last_stats_signature = signature
                    self._frozen_frame_count = 0
                if self._frozen_frame_count >= max_consecutive_failures:
                    print(f"[camera] frame content unchanged for {self._frozen_frame_count} reads, disconnecting (stalled driver/USB, not a real dropped connection)")
                    _append_csv_row(
                        CAMERA_FREEZE_LOG_PATH,
                        ["timestamp_utc", "frozen_frame_count", "stale_mean", "stale_max"],
                        [datetime.now(timezone.utc).isoformat(timespec="seconds"), self._frozen_frame_count, stats["mean"], stats["max"]],
                    )
                    with self._lock:
                        self._disconnect_locked(
                            f"Camera index {self.index} stopped updating (identical frames). "
                            "Check the camera index: a virtual camera may show only a placeholder."
                        )
                    break

                predicted_xy = _predict_xy(self._prior_target_xy, self._prior_velocity_xy)
                regions = locate_bright_regions(region, prior_xy=predicted_xy)
                if regions["x"] is not None:
                    self._prior_velocity_xy = _update_velocity_xy(
                        self._prior_target_xy, self._prior_velocity_xy, (regions["x"], regions["y"])
                    )
                    self._prior_target_xy = (regions["x"], regions["y"])
                offset_x, offset_y = (roi[0], roi[1]) if roi is not None else (0, 0)
                for b in regions["blobs"]:
                    b["x"] += offset_x
                    b["y"] += offset_y
                    px, py = int(round(b["x"])), int(round(b["y"]))
                    color = (0, 255, 0) if b["kind"] == "red" else (0, 255, 255)  # green=red glow, yellow=white core
                    radius = max(6, int(round(b["area"] ** 0.5)))
                    cv2.circle(frame, (px, py), radius, color, 2)
                if regions["x"] is not None:
                    regions["x"] += offset_x
                    regions["y"] += offset_y
                    wx, wy = int(round(regions["x"])), int(round(regions["y"]))
                    cv2.drawMarker(frame, (wx, wy), (255, 0, 255), cv2.MARKER_CROSS, 22, 2)  # magenta = composite peak

                ok2, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, CAMERA_JPEG_QUALITY])
                if ok2:
                    with self._lock:
                        self._latest_jpeg = buf.tobytes()
                        self._latest_stats = stats
                        self._latest_regions = regions
                        # Timestamp AFTER cap.read() returns, not before -- this is
                        # what a caller compares a move-completion time against to
                        # know a frame was actually grabbed after the move, not
                        # picked up mid-flight from the driver's internal buffer.
                        self._latest_frame_time = time.monotonic()
            else:
                consecutive_failures += 1
                if consecutive_failures >= max_consecutive_failures:
                    print(f"[camera] {consecutive_failures} consecutive grabFrame failures, disconnecting")
                    with self._lock:
                        self._disconnect_locked(
                            f"Camera index {self.index} stopped delivering video frames. "
                            "Check its USB connection and camera index."
                        )
                    break
            elapsed = time.monotonic() - started
            time.sleep(max(0.0, interval - elapsed))

    def _status_locked(self) -> dict:
        return {
            "connected": self.connected,
            "index": self.index,
            "error": self.error,
            "roi": list(self.roi) if self.roi else None,
            "brightness": dict(self._latest_stats),
            "peak": dict(self._latest_regions) if self._latest_regions else None,
            "frameTime": self._latest_frame_time,
        }

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def wait_for_fresh(self, after_time: float, timeout: float = 2.0, poll_interval: float = 0.01) -> dict:
        """Block until a frame captured strictly after `after_time` is
        available (or timeout), then return status(). Use this instead of a
        fixed sleep-then-read after moving Z: the capture loop runs on its
        own ~15fps cadence independent of the move, so a blind dwell can
        still hand back a frame grabbed mid-move (or, with a slow-exposure
        camera in low light, one whose exposure window straddled the move).
        Waiting for a *timestamped* post-move frame removes that class of
        error instead of guessing a dwell long enough to usually avoid it.
        Returns the latest status on timeout rather than raising -- callers
        that care should check the returned frameTime themselves."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self.connected:
                    raise RuntimeError("Camera not connected.")
                if self._latest_frame_time > after_time:
                    return self._status_locked()
            time.sleep(poll_interval)
        with self._lock:
            return self._status_locked()

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg


CAMERA = CameraController()


def prepare_wsl_bridge() -> None:
    """Prepare this project's local bridge, without any stage commands."""
    if os.name != "nt":
        raise RuntimeError("Automatic WSL preparation is available on Windows only.")
    script = ROOT / "tools" / "start_esp300_bridge.ps1"
    (ROOT / "logs").mkdir(exist_ok=True)
    log_path = ROOT / "logs" / "wsl-prepare-last.log"
    try:
        # A detached WSL descendant may inherit pipe handles. communicate()
        # would then wait for bridge exit even after PowerShell has exited.
        # A file lets us wait only for the finite preparation process.
        with log_path.open("wb") as output:
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-PrepareOnly"],
                cwd=str(ROOT), stdout=output, stderr=subprocess.STDOUT,
                timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("WSL 준비 시간 초과. 관리자 승인 창 또는 USB 연결을 확인한 뒤 Connect를 다시 누르세요.") from exc
    if result.returncode:
        raise RuntimeError("WSL USB/bridge 준비 실패: " + log_path.read_text(encoding="utf-8", errors="replace").strip()[-1800:])


def connect_jog_request(request: dict) -> dict:
    """Serialize connection changes; auto-clean only an idle simulated session."""
    if not CONNECTION_LOCK.acquire(blocking=False):
        raise RuntimeError("연결 준비가 진행 중입니다. 완료를 기다려 주세요.")
    try:
        port = request.get("port", "COM5")
        baud = request.get("baudrate", JOG_DEFAULT_BAUDRATE)
        dry = request.get("dryRun", True)
        auto = request.get("prepareWsl") is True
        if not auto:
            return JOG.connect(port, baud, dry)
        if port != "rfc2217://127.0.0.1:22170" or dry is not False:
            raise RuntimeError("Use WSL requires the local WSL bridge and Live mode.")
        with JOG._lock:
            JOG._require_no_sensor_home_locked()
            JOG._require_no_run_locked()
            JOG._require_manual_still_locked()
            if JOG.connected and not JOG.dry_run and (JOG.port != port or JOG.baudrate != int(baud)):
                raise RuntimeError("다른 실제 장비 연결이 있습니다. Disconnect 후 다시 연결하세요.")
        if JOG.connected and JOG.dry_run:
            JOG.disconnect()
        CONNECTION_PREPARATION.update(active=True, phase="기존 연결 확인", error=None)
        generation = JOG._poll_generation
        if not JOG.connected:
            CONNECTION_PREPARATION["phase"] = "USB 연결 및 WSL 브리지 준비 중 — 최초 공유는 Windows 관리자 승인이 필요할 수 있습니다."
            prepare_wsl_bridge()
        if generation != JOG._poll_generation:
            raise RuntimeError("연결 준비 중 세션이 변경되어 취소됐습니다.")
        CONNECTION_PREPARATION["phase"] = "실제 제어기 응답 확인 중 (VE)"
        probe = JOG.probe_link(port, baud)
        CONNECTION_PREPARATION["phase"] = "실제 장비 연결 중"
        result = JOG.connect(port, baud, False, expected_generation=generation)
        result["versionReply"] = probe["versionReply"]
        result["connectionPreparation"] = {"active": False, "phase": None, "error": None}
        return result
    except Exception as exc:
        CONNECTION_PREPARATION["error"] = str(exc)
        raise
    finally:
        CONNECTION_PREPARATION.update(active=False, phase=None)
        CONNECTION_LOCK.release()


def optional_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def float_or_default(value: object, default: float) -> float:
    parsed = optional_float(value)
    return default if parsed is None else parsed


def safe_file_stem(name: object) -> str:
    stem = Path(str(name or "design")).stem
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("._")
    return safe or "design"


def path_length(points: list[tuple[float, float]]) -> float:
    return sum(distance(a, b) for a, b in zip(points, points[1:]))


def path_bbox(points: list[tuple[float, float]]) -> dict:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {
        "minX": min(xs),
        "minY": min(ys),
        "maxX": max(xs),
        "maxY": max(ys),
        "width": max(xs) - min(xs),
        "height": max(ys) - min(ys),
    }


def bbox_payload(paths: list[LaserPath]) -> dict:
    (min_x, min_y), (max_x, max_y) = raw_bbox(paths)
    return {
        "minX": min_x,
        "minY": min_y,
        "maxX": max_x,
        "maxY": max_y,
        "width": max_x - min_x,
        "height": max_y - min_y,
    }


def default_bbox_payload(size: float = DEFAULT_LONGEST_SIDE_MM) -> dict:
    return {
        "minX": 0.0,
        "minY": 0.0,
        "maxX": size,
        "maxY": size,
        "width": size,
        "height": size,
    }


def glass_size_from_metadata(metadata: dict | None = None) -> tuple[float, float]:
    raw = (metadata or {}).get("glass_size_mm", DEFAULT_GLASS_SIZE_MM)
    if isinstance(raw, (int, float)):
        width = height = float(raw)
    else:
        values = list(raw) if isinstance(raw, (list, tuple)) else list(DEFAULT_GLASS_SIZE_MM)
        width = float(values[0]) if values else DEFAULT_GLASS_SIZE_MM[0]
        height = float(values[1]) if len(values) > 1 else width
    return max(width, 0.001), max(height, 0.001)


def glass_start_xy_from_metadata(metadata: dict | None = None) -> tuple[float, float]:
    width, height = glass_size_from_metadata(metadata)
    raw = (metadata or {}).get("start_xy_mm")
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        return float(raw[0]), float(raw[1])
    usable_center = (metadata or {}).get("usable_center_xy_mm")
    if isinstance(usable_center, (list, tuple)) and len(usable_center) >= 2:
        return float(usable_center[0]), float(usable_center[1])
    return width / 2.0, height / 2.0


def default_glass_metadata() -> dict:
    width, height = DEFAULT_GLASS_SIZE_MM
    center = [width / 2.0, height / 2.0]
    return {
        "glass_size_mm": [width, height],
        "start_xy_mm": center,
        "usable_area_shape": "circle",
        "usable_diameter_mm": min(width, height),
        "usable_center_xy_mm": center,
        "usable_margin_mm": DEFAULT_USABLE_MARGIN_MM,
    }


def glass_bbox_payload(metadata: dict | None = None) -> dict:
    width, height = glass_size_from_metadata(metadata)
    return {
        "minX": 0.0,
        "minY": 0.0,
        "maxX": width,
        "maxY": height,
        "width": width,
        "height": height,
    }


def detected_circle_diameters(paths: list[LaserPath]) -> list[float]:
    diameters: list[float] = []
    for laser_path in paths:
        if len(laser_path.points) < 12:
            continue
        if not laser_path.closed and distance(laser_path.points[0], laser_path.points[-1]) > 1e-6:
            continue
        box = path_bbox(laser_path.points)
        diameter = (box["width"] + box["height"]) / 2.0
        if diameter <= 0:
            continue
        roundness = abs(box["width"] - box["height"]) / diameter
        circumference = path_length(laser_path.points)
        circle_error = abs(circumference - math.pi * diameter) / max(math.pi * diameter, 1e-9)
        if roundness <= 0.08 and circle_error <= 0.15:
            diameters.append(diameter)
    return sorted(diameters)


def circle_check(paths: list[LaserPath], target_diameter: float | None) -> dict | None:
    diameters = detected_circle_diameters(paths)
    if not diameters:
        return None
    median = diameters[len(diameters) // 2]
    result = {
        "count": len(diameters),
        "detected_diameter_mm": median,
        "min_diameter_mm": min(diameters),
        "max_diameter_mm": max(diameters),
    }
    if target_diameter:
        result["target_diameter_mm"] = target_diameter
        result["difference_mm"] = median - target_diameter
        result["difference_percent"] = ((median - target_diameter) / target_diameter) * 100.0
    return result


def laser_path_to_payload(index: int, laser_path: LaserPath, *, passes: int = 1, selected: bool = True) -> dict:
    points = [(float(x), float(y)) for x, y in laser_path.points]
    return {
        "id": index,
        "layer": decode_dxf_unicode_escapes(laser_path.layer),
        "rawLayer": laser_path.layer,
        "entityType": laser_path.entity_type,
        "closed": laser_path.closed,
        "points": [[round(x, 6), round(y, 6)] for x, y in points],
        "length": path_length(points),
        "bbox": path_bbox(points),
        "passes": max(1, int(passes)),
        "selected": bool(selected),
    }


def payload_to_laser_path(payload: dict) -> LaserPath:
    return LaserPath(
        points=[(float(x), float(y)) for x, y in payload["points"]],
        layer=payload.get("rawLayer") or payload.get("layer", "0"),
        entity_type=payload.get("entityType", "PATH"),
        closed=bool(payload.get("closed", False)),
    )


def load_generated_script(script_path: Path) -> tuple[list[dict], dict]:
    spec = importlib.util.spec_from_file_location(f"generated_{script_path.stem}", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PATHS, module.METADATA


def build_segments(
    paths: list[LaserPath],
    metadata: dict,
    *,
    base_ids: list[int] | None = None,
    pass_indices: list[int] | None = None,
) -> dict:
    feed_rate = float(metadata.get("feed_rate", DEFAULT_FEED_RATE_MM_S))
    travel_rate = float(metadata.get("travel_rate", DEFAULT_TRAVEL_RATE_MM_S))
    focus_z = float(metadata.get("focus_z_mm", DEFAULT_FOCUS_Z_MM))
    drawing_depth = float(metadata.get("drawing_depth_mm", 0.0))
    if not math.isfinite(drawing_depth) or drawing_depth < 0:
        raise ValueError("Drawing entry depth must be a finite non-negative distance in mm.")
    cut_z = focus_z + drawing_depth
    z_defocus_mm = abs(float(metadata.get("z_defocus_mm", DEFAULT_Z_DEFOCUS_MM)))
    defocus_z = focus_z - z_defocus_mm
    z_speed = max(float(metadata.get("z_speed_mm_s", DEFAULT_Z_SPEED_MM_S)), 0.001)
    position_tolerance = max(float(metadata.get("position_tolerance_mm", DEFAULT_POSITION_TOLERANCE_MM)), 0.0)
    segments: list[dict] = []
    cut_length = 0.0
    travel_length = 0.0
    z_length = 0.0
    current = glass_start_xy_from_metadata(metadata)
    current_z = focus_z
    all_points = [current]

    def point3(point: tuple[float, float], z: float) -> list[float]:
        return [round(float(point[0]), 6), round(float(point[1]), 6), round(float(z), 6)]

    def add_z_segment(kind: str, point: tuple[float, float], target_z: float, source_id: int, layer: str) -> None:
        nonlocal current_z, z_length
        distance_z = abs(target_z - current_z)
        if distance_z <= 1e-9:
            current_z = target_z
            return
        segments.append(
            {
                "kind": kind,
                "pathIndex": source_id,
                "from": [round(float(point[0]), 6), round(float(point[1]), 6)],
                "to": [round(float(point[0]), 6), round(float(point[1]), 6)],
                "from3": point3(point, current_z),
                "to3": point3(point, target_z),
                "length": distance_z,
                "duration": distance_z / z_speed,
                "speedMmS": z_speed,
                "layer": layer,
                "laserOn": False,
                "zOnly": True,
            }
        )
        z_length += distance_z
        current_z = target_z

    for index, laser_path in enumerate(paths):
        points = [(float(x), float(y)) for x, y in laser_path.points]
        if len(points) < 2:
            continue
        source_id = base_ids[index] if base_ids and index < len(base_ids) else index
        layer = decode_dxf_unicode_escapes(laser_path.layer)
        first = points[0]
        travel = distance(current, first)
        # Always establish clearance, the first XY start, then focus. A
        # second run may start at the previous endpoint/defocus height even
        # when this path's first point equals the nominal design center.
        if index == 0 or travel > position_tolerance:
            add_z_segment("z-defocus", current, defocus_z, source_id, layer)
            segments.append(
                {
                    "kind": "travel",
                    "pathIndex": source_id,
                    "from": [round(current[0], 6), round(current[1], 6)],
                    "to": [round(first[0], 6), round(first[1], 6)],
                    "from3": point3(current, current_z),
                    "to3": point3(first, current_z),
                    "length": travel,
                    "duration": max(travel / travel_rate, 0.05),
                    "speedMmS": travel_rate,
                    "layer": layer,
                    "laserOn": False,
                }
            )
            travel_length += travel
            all_points.append(first)
        current = first
        # Focus retreats by Z_STEP_BACK_MM every Z_STEP_BACK_PASSES repeats
        # of a path, along the defocus direction, to compensate for
        # material recession over multiple passes.
        pass_index = pass_indices[index] if pass_indices and index < len(pass_indices) else 0
        pass_focus_z = cut_z - (pass_index // Z_STEP_BACK_PASSES) * Z_STEP_BACK_MM
        add_z_segment("z-focus", current, pass_focus_z, source_id, layer)

        for start, end in zip(points, points[1:]):
            length = distance(start, end)
            if length <= 1e-9:
                continue
            segments.append(
                {
                    "kind": "cut",
                    "pathIndex": source_id,
                    "from": [round(start[0], 6), round(start[1], 6)],
                    "to": [round(end[0], 6), round(end[1], 6)],
                    "from3": point3(start, current_z),
                    "to3": point3(end, current_z),
                    "length": length,
                    "duration": length / feed_rate,
                    "speedMmS": feed_rate,
                    "layer": layer,
                    "laserOn": True,
                }
            )
            cut_length += length
            all_points.extend([start, end])
            current = end

    if paths:
        final_source_id = base_ids[-1] if base_ids else len(paths) - 1
        add_z_segment("z-defocus", current, defocus_z, final_source_id, "final")

    glass_width, glass_height = glass_size_from_metadata(metadata)
    box = path_bbox(all_points + [(0.0, 0.0), (glass_width, glass_height)])
    return {
        "metadata": metadata,
        "bbox": box,
        "stats": {
            "segments": len(segments),
            "scheduledPaths": len(paths),
            "cutLength": cut_length,
            "travelLength": travel_length,
            "zLength": z_length,
            "totalLength": cut_length + travel_length,
            "motionLength3d": cut_length + travel_length + z_length,
            "duration": sum(segment["duration"] for segment in segments),
            "points": sum(len(path.points) for path in paths),
        },
        "segments": segments,
    }


def build_motion_from_script(script_key: str) -> dict:
    script_path = SCRIPT_CHOICES.get(script_key, SCRIPT_CHOICES["full"])
    paths, metadata = load_generated_script(script_path)
    laser_paths = [
        LaserPath(
            points=[(float(x), float(y)) for x, y in path["points"]],
            layer=path.get("layer", "0"),
            entity_type=path.get("entity_type", "PATH"),
            closed=bool(path.get("closed", False)),
        )
        for path in paths
    ]
    payload = build_segments(laser_paths, metadata)
    payload["script"] = script_key
    payload["scriptPath"] = str(script_path)
    payload["stats"]["paths"] = len(laser_paths)
    return payload


def expand_passes(
    order: list[LaserPath], pass_counts: dict[int, int], ordered_ids: list[int]
) -> tuple[list[LaserPath], list[int], list[int]]:
    scheduled: list[LaserPath] = []
    scheduled_ids: list[int] = []
    scheduled_pass_indices: list[int] = []
    current: tuple[float, float] | None = None

    for laser_path, path_id in zip(order, ordered_ids):
        passes = max(0, int(pass_counts.get(path_id, 1)))
        if passes <= 0:
            continue

        points = list(laser_path.points)
        if current is not None:
            forward = distance(current, points[0])
            backward = distance(current, points[-1])
            if backward < forward:
                points = list(reversed(points))

        for pass_index in range(passes):
            pass_points = points if pass_index % 2 == 0 or laser_path.closed else list(reversed(points))
            scheduled.append(
                LaserPath(
                    points=list(pass_points),
                    layer=laser_path.layer,
                    entity_type=laser_path.entity_type,
                    closed=laser_path.closed,
                )
            )
            scheduled_ids.append(path_id)
            scheduled_pass_indices.append(pass_index)
            current = pass_points[-1]

    return scheduled, scheduled_ids, scheduled_pass_indices


def endpoint_after_passes(laser_path: LaserPath, passes: int) -> tuple[float, float]:
    if laser_path.closed or passes % 2 == 1:
        return laser_path.points[-1]
    return laser_path.points[0]


def item_travel_cost(
    items: list[tuple[int, LaserPath]],
    pass_counts: dict[int, int],
    start: tuple[float, float] = (0.0, 0.0),
) -> float:
    current = start
    cost = 0.0
    for path_id, laser_path in items:
        oriented = orient_path_from_current(laser_path, current)
        cost += distance(current, oriented.points[0])
        current = endpoint_after_passes(oriented, max(1, int(pass_counts.get(path_id, 1))))
    return cost


def orient_items(
    items: list[tuple[int, LaserPath]],
    pass_counts: dict[int, int],
    start: tuple[float, float] = (0.0, 0.0),
) -> tuple[list[LaserPath], list[int]]:
    current = start
    oriented_paths: list[LaserPath] = []
    ordered_ids: list[int] = []
    for path_id, laser_path in items:
        oriented = orient_path_from_current(laser_path, current)
        oriented_paths.append(oriented)
        ordered_ids.append(path_id)
        current = endpoint_after_passes(oriented, max(1, int(pass_counts.get(path_id, 1))))
    return oriented_paths, ordered_ids


def optimize_items(
    items: list[tuple[int, LaserPath]],
    pass_counts: dict[int, int],
    start: tuple[float, float] = (0.0, 0.0),
) -> tuple[list[LaserPath], list[int]]:
    remaining = list(items)
    ordered: list[tuple[int, LaserPath]] = []
    current = start

    while remaining:
        best_index = min(
            range(len(remaining)),
            key=lambda index: distance(current, orient_path_from_current(remaining[index][1], current).points[0]),
        )
        path_id, laser_path = remaining.pop(best_index)
        oriented = orient_path_from_current(laser_path, current)
        ordered.append((path_id, oriented))
        current = endpoint_after_passes(oriented, max(1, int(pass_counts.get(path_id, 1))))

    # Every 2-opt candidate reorients and rescans the whole route. This is
    # cubic work for hundreds of annotation/entity paths and can leave the
    # browser waiting for minutes. Keep the nearest-neighbor optimization
    # for large drawings; the bounded small-drawing refinement is unchanged.
    if len(ordered) > 64:
        return orient_items(ordered, pass_counts, start)

    best_cost = item_travel_cost(ordered, pass_counts, start)
    for _ in range(2):
        improved = False
        for i in range(0, len(ordered) - 2):
            for j in range(i + 2, len(ordered)):
                candidate = ordered[:i] + list(reversed(ordered[i : j + 1])) + ordered[j + 1 :]
                cost = item_travel_cost(candidate, pass_counts, start)
                if cost + 1e-6 < best_cost:
                    ordered = candidate
                    best_cost = cost
                    improved = True
                    break
            if improved:
                break
        if not improved:
            break

    return orient_items(ordered, pass_counts, start)


def build_plan(session: dict, request: dict) -> dict:
    if "paths" in request:
        selected = request.get("paths") or []
    else:
        selected = [
            {"id": path["id"], "passes": path.get("passes", 1)}
            for path in session["paths"]
            if path.get("selected", True)
        ]

    pass_counts = {int(item["id"]): max(0, int(item.get("passes", 1))) for item in selected}
    selected_ids = [path_id for path_id, count in pass_counts.items() if count > 0]
    path_by_id = {int(path["id"]): payload_to_laser_path(path) for path in session["paths"]}
    selected_paths = [path_by_id[path_id] for path_id in selected_ids if path_id in path_by_id]
    selected_ids = [path_id for path_id in selected_ids if path_id in path_by_id]

    if not selected_paths:
        raise ValueError("No selected paths with pass count > 0.")

    start_xy = glass_start_xy_from_metadata(session["metadata"])
    optimize = bool(request.get("optimize", True))
    if optimize:
        optimized_paths, ordered_ids = optimize_items(list(zip(selected_ids, selected_paths)), pass_counts, start=start_xy)
    else:
        optimized_paths = selected_paths
        ordered_ids = selected_ids

    scheduled_paths, scheduled_ids, scheduled_pass_indices = expand_passes(optimized_paths, pass_counts, ordered_ids)
    metadata = {
        **default_glass_metadata(),
        **session["metadata"],
        "feed_rate": float(request.get("feedRate", session["metadata"].get("feed_rate", DEFAULT_FEED_RATE_MM_S))),
        "travel_rate": float(request.get("travelRate", session["metadata"].get("travel_rate", DEFAULT_TRAVEL_RATE_MM_S))),
        "selected_path_count": len(selected_paths),
        "scheduled_path_count": len(scheduled_paths),
        "path_passes": pass_counts,
        "optimize": optimize,
        "focus_z_mm": float(request.get("focusZMm", session["metadata"].get("focus_z_mm", DEFAULT_FOCUS_Z_MM))),
        "drawing_depth_mm": float(request.get("drawingDepthMm", session["metadata"].get("drawing_depth_mm", 0.0))),
        "z_defocus_mm": float(request.get("zDefocusMm", session["metadata"].get("z_defocus_mm", DEFAULT_Z_DEFOCUS_MM))),
        "z_speed_mm_s": float(request.get("zSpeedMmS", session["metadata"].get("z_speed_mm_s", DEFAULT_Z_SPEED_MM_S))),
        "position_tolerance_mm": float(
            request.get("positionTolerance", session["metadata"].get("position_tolerance_mm", DEFAULT_POSITION_TOLERANCE_MM))
        ),
    }
    payload = build_segments(scheduled_paths, metadata, base_ids=scheduled_ids, pass_indices=scheduled_pass_indices)
    payload["sessionId"] = session["id"]
    payload["selectedIds"] = selected_ids
    payload["scheduledIds"] = scheduled_ids
    payload["stats"]["paths"] = len(selected_paths)
    payload["stats"]["passes"] = sum(pass_counts[path_id] for path_id in selected_ids)
    payload["paths"] = [
        {
            "id": path_id,
            "passes": pass_counts[path_id],
            "length": path_by_id[path_id].length,
        }
        for path_id in selected_ids
    ]
    payload["_scheduledPaths"] = scheduled_paths
    return payload


def trace_file(source: Path, params: dict) -> dict:
    if not source.exists():
        raise FileNotFoundError(source)

    trace_mode = params.get("traceMode", "design")
    fit_width_mm = optional_float(params.get("fitWidthMm"))
    fit_height_mm = optional_float(params.get("fitHeightMm"))
    fit_longest_mm = float_or_default(params.get("fitLongestMm"), DEFAULT_LONGEST_SIDE_MM)
    flatness_mm = float_or_default(params.get("flatnessMm"), 0.02)
    min_length_mm = float_or_default(params.get("minLengthMm"), 0.001)
    feed_rate = float_or_default(params.get("feedRate"), DEFAULT_FEED_RATE_MM_S)
    travel_rate = float_or_default(params.get("travelRate"), DEFAULT_TRAVEL_RATE_MM_S)
    rotation_deg = float_or_default(params.get("rotationDeg"), DEFAULT_ROTATION_DEG)

    session_id = uuid.uuid4().hex[:12]
    output_stub = GENERATED_ROOT / f"{source.stem}_{session_id}_esp300.py"
    dxf_path = ensure_dxf(source, output_stub)
    skipped: dict[str, int] = {}
    raw_paths, _doc, skipped = extract_paths(
        dxf_path,
        include_layers=params.get("includeLayers", []),
        exclude_layers=params.get("excludeLayers", []),
        flatness_mm=flatness_mm,
        unit_scale=CURVE_FLATTENING_SCALE_HINT,
        min_length_mm=min_length_mm,
        skip_watermark=False,
    )
    # Preserve the previously supported legacy filter's pre-fit behavior.
    raw_paths = skip_known_aspose_watermark(raw_paths, skipped, include_framed=False)
    if trace_mode == "design" and not params.get("includeLayers"):
        raw_paths = select_design_paths(raw_paths, skipped)
    kept_ids = {id(p) for p in skip_known_aspose_watermark(raw_paths, skipped)}
    keep_mask = [id(p) in kept_ids for p in raw_paths]
    if not kept_ids:
        raise RuntimeError("No drawable paths found after trace filters.")

    # Rotate the drawing about its own center before fit scaling; for a
    # non-square layout this can increase usable margin within the
    # circular working area.
    raw_paths = rotate_paths(raw_paths, rotation_deg)

    glass_meta = default_glass_metadata()
    usable_diameter_mm = float(params.get("usableDiameterMm", glass_meta["usable_diameter_mm"]))
    usable_margin_mm = float(params.get("usableMarginMm", glass_meta["usable_margin_mm"]))
    glass_meta["usable_diameter_mm"] = usable_diameter_mm
    glass_meta["usable_margin_mm"] = usable_margin_mm
    usable_center_xy = glass_meta["usable_center_xy_mm"]

    scale = apply_fit_scale(
        raw_paths,
        CURVE_FLATTENING_SCALE_HINT,
        fit_width_mm,
        fit_height_mm,
        fit_longest_mm,
    )
    scale = cap_scale_to_circle(raw_paths, scale, diameter_mm=usable_diameter_mm, margin_mm=usable_margin_mm)
    machine_paths, source_bbox, machine_bbox = transform_paths(
        raw_paths,
        unit_scale=scale,
        origin=(float(usable_center_xy[0]), float(usable_center_xy[1])),
        anchor="center",
        flip_x=bool(params.get("flipX", False)),
        flip_y=bool(params.get("flipY", False)),
        max_segment_mm=float(params.get("maxSegmentMm", 0.0)),
    )

    # Keep the original fit/rotation frame so hiding converter outlines does
    # not resize or move the user's existing design on the stage.
    machine_paths = [p for p, keep in zip(machine_paths, keep_mask) if keep]
    payload_paths = [laser_path_to_payload(index, laser_path) for index, laser_path in enumerate(machine_paths)]
    circle_info = circle_check(machine_paths, FIXED_REFERENCE_CIRCLE_DIAMETER_MM)
    metadata = {
        **glass_meta,
        "source": str(source),
        "dxf": str(dxf_path),
        "unit_scale": scale,
        "machine_unit": "mm",
        "origin": [float(usable_center_xy[0]), float(usable_center_xy[1])],
        "anchor": "center",
        "feed_rate": feed_rate,
        "travel_rate": travel_rate,
        "focus_z_mm": DEFAULT_FOCUS_Z_MM,
        "z_defocus_mm": DEFAULT_Z_DEFOCUS_MM,
        "z_speed_mm_s": DEFAULT_Z_SPEED_MM_S,
        "trace_mode": trace_mode,
        "fit_width_mm": fit_width_mm,
        "fit_height_mm": fit_height_mm,
        "fit_longest_mm": fit_longest_mm,
        "rotation_deg": rotation_deg,
        "reference_circle_diameter_mm": FIXED_REFERENCE_CIRCLE_DIAMETER_MM,
        "circle_check": circle_info,
        "path_count": len(machine_paths),
        "point_count": sum(len(path.points) for path in machine_paths),
        "total_length_mm": round(sum(path.length for path in machine_paths), 6),
        "skipped": skipped,
    }
    session = {
        "id": session_id,
        "sourceName": source.name,
        "sourcePath": str(source),
        "dxfPath": str(dxf_path),
        "metadata": metadata,
        "bbox": glass_bbox_payload(metadata),
        "rawBbox": {
            "minX": source_bbox[0][0],
            "minY": source_bbox[0][1],
            "maxX": source_bbox[1][0],
            "maxY": source_bbox[1][1],
        },
        "machineBbox": {
            "minX": machine_bbox[0][0],
            "minY": machine_bbox[0][1],
            "maxX": machine_bbox[1][0],
            "maxY": machine_bbox[1][1],
        },
        "paths": payload_paths,
    }
    SESSIONS[session_id] = session
    return session


def manual_path_from_payload(payload: dict) -> tuple[LaserPath, int, bool] | None:
    raw_points = payload.get("points") or []
    points: list[tuple[float, float]] = []
    for raw_point in raw_points:
        if not isinstance(raw_point, (list, tuple)) or len(raw_point) < 2:
            continue
        x = float(raw_point[0])
        y = float(raw_point[1])
        if math.isfinite(x) and math.isfinite(y):
            points.append((x, y))

    points = close_duplicate_points(points)
    closed = bool(payload.get("closed", False))
    if closed and len(points) > 2 and distance(points[0], points[-1]) > 1e-7:
        points.append(points[0])

    if len(points) < 2 or path_length(points) <= 1e-9:
        return None

    layer = str(payload.get("layer") or "직접 조합")
    entity_type = str(payload.get("entityType") or payload.get("entity_type") or "MANUAL")
    passes = max(1, int(payload.get("passes", 1)))
    selected = bool(payload.get("selected", True))
    return LaserPath(points=points, layer=layer, entity_type=entity_type, closed=closed), passes, selected


def close_duplicate_points(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    cleaned: list[tuple[float, float]] = []
    for point in points:
        if not cleaned or distance(cleaned[-1], point) > 1e-9:
            cleaned.append(point)
    return cleaned


def build_manual_session(request: dict) -> dict:
    session_id = uuid.uuid4().hex[:12]
    name = str(request.get("name") or "manual_design")
    feed_rate = float_or_default(request.get("feedRate"), DEFAULT_FEED_RATE_MM_S)
    travel_rate = float_or_default(request.get("travelRate"), DEFAULT_TRAVEL_RATE_MM_S)

    parsed_paths: list[tuple[LaserPath, int, bool]] = []
    for payload in request.get("paths") or []:
        if not isinstance(payload, dict):
            continue
        parsed = manual_path_from_payload(payload)
        if parsed is not None:
            parsed_paths.append(parsed)

    laser_paths = [item[0] for item in parsed_paths]
    payload_paths = [
        laser_path_to_payload(index, laser_path, passes=passes, selected=selected)
        for index, (laser_path, passes, selected) in enumerate(parsed_paths)
    ]
    box = bbox_payload(laser_paths) if laser_paths else default_bbox_payload()
    circle_info = circle_check(laser_paths, FIXED_REFERENCE_CIRCLE_DIAMETER_MM) if laser_paths else None
    metadata = {
        **default_glass_metadata(),
        "source": name,
        "dxf": None,
        "source_type": "manual",
        "unit_scale": 1.0,
        "machine_unit": "mm",
        "origin": [0.0, 0.0],
        "anchor": "drawing-origin",
        "feed_rate": feed_rate,
        "travel_rate": travel_rate,
        "focus_z_mm": DEFAULT_FOCUS_Z_MM,
        "z_defocus_mm": DEFAULT_Z_DEFOCUS_MM,
        "z_speed_mm_s": DEFAULT_Z_SPEED_MM_S,
        "trace_mode": "manual",
        "fit_width_mm": None,
        "fit_height_mm": None,
        "fit_longest_mm": None,
        "reference_circle_diameter_mm": FIXED_REFERENCE_CIRCLE_DIAMETER_MM,
        "circle_check": circle_info,
        "path_count": len(laser_paths),
        "point_count": sum(len(path.points) for path in laser_paths),
        "total_length_mm": round(sum(path.length for path in laser_paths), 6),
        "skipped": {},
    }
    session = {
        "id": session_id,
        "sourceName": name,
        "sourcePath": None,
        "dxfPath": None,
        "metadata": metadata,
        "bbox": glass_bbox_payload(metadata),
        "rawBbox": box,
        "machineBbox": box,
        "paths": payload_paths,
    }
    SESSIONS[session_id] = session
    return session


class VisualizerHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/substrate/"):
            from integrated_substrate import dispatch
            dispatch(self, globals(), parsed.path.rsplit("/", 1)[-1])
            return
        if parsed.path == "/api/motion":
            query = parse_qs(parsed.query)
            script_key = query.get("script", ["full"])[0]
            self.send_json(build_motion_from_script(script_key))
            return
        if parsed.path == "/api/default":
            self.handle_default()
            return
        if parsed.path == "/api/session":
            query = parse_qs(parsed.query)
            session_id = query.get("id", [""])[0]
            session = SESSIONS.get(session_id)
            if not session:
                self.send_error_json(404, "Unknown session.")
                return
            self.send_json(session)
            return
        if parsed.path == "/api/download":
            self.handle_download(parsed)
            return
        if parsed.path == "/api/jog/status":
            self.send_json(JOG.status())
            return
        if parsed.path == "/api/serial/ports":
            self.send_json({"ports": list_serial_ports()})
            return
        if parsed.path == "/api/run/status":
            self.send_json(JOG.run_status())
            return
        if parsed.path == "/api/run/plan":
            self.send_json(JOG.run_snapshot())
            return
        if parsed.path == "/api/run/records":
            self.send_json(JOG.run_records(int(parse_qs(parsed.query).get("after", ["0"])[0])))
            return
        if parsed.path == "/api/camera/status":
            self.send_json(CAMERA.status())
            return
        if parsed.path == "/api/camera/stream":
            self.handle_camera_stream()
            return
        path = parsed.path.lstrip("/") or "index.html"
        target = (STATIC_ROOT / path).resolve()
        if not str(target).startswith(str(STATIC_ROOT.resolve())) or not target.exists():
            self.send_error(404)
            return

        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/substrate/"):
            from integrated_substrate import dispatch
            dispatch(self, globals(), parsed.path.rsplit("/", 1)[-1])
            return
        app_audit.emit("http_request", method="POST", path=parsed.path)
        try:
            if parsed.path == "/api/depth/preview":
                self.read_json()
                with JOG._lock:
                    context = DEPTH_CONTEXT.observe(JOG, JOG_AXES, ESP300_AXIS_SIGNS)
                self.send_json(build_recipe(context))
            elif parsed.path == "/api/depth/validate":
                request = self.read_json()
                with JOG._lock:
                    context = DEPTH_CONTEXT.observe(JOG, JOG_AXES, ESP300_AXIS_SIGNS)
                self.send_json(validate_recipe(request.get("recipe", {}), context))
            elif parsed.path == "/api/depth/execute":
                raise RuntimeError("Depth recipe execution is disabled; offline preview only.")
            elif parsed.path == "/api/audit/status":
                self.send_json(app_audit.RECORDER.health())
            elif parsed.path == "/api/server/stop":
                if JOG.run_status()["running"]:
                    raise RuntimeError("A machine operation is running. Stop physical motion before shutting down the server.")
                self.send_json({"stopping": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif parsed.path == "/api/trace":
                self.handle_trace()
            elif parsed.path == "/api/manual":
                self.send_json(build_manual_session(self.read_json()))
            elif parsed.path == "/api/plan":
                request = self.read_json()
                session = SESSIONS.get(request.get("sessionId", ""))
                if not session:
                    self.send_error_json(404, "Unknown session.")
                    return
                plan = build_plan(session, request)
                plan.pop("_scheduledPaths", None)
                self.send_json(plan)
            elif parsed.path == "/api/export":
                self.handle_export()
            elif parsed.path == "/api/jog/probe":
                request = self.read_json()
                self.send_json(JOG.probe_link(request.get("port", "COM5"), request.get("baudrate", JOG_DEFAULT_BAUDRATE)))
            elif parsed.path == "/api/jog/z-limit":
                self.send_json(JOG.set_z_max(self.read_json().get("zMaxMm")))
            elif parsed.path == "/api/jog/connect":
                request = self.read_json()
                self.send_json(connect_jog_request(request))
            elif parsed.path == "/api/jog/disconnect":
                self.send_json(JOG.disconnect())
            elif parsed.path == "/api/jog/move":
                request = self.read_json()
                self.send_json(JOG.move(request.get("axis", ""), request.get("deltaMm", 0), request.get("speedMmS", 0.5)))
            elif parsed.path == "/api/jog/estop":
                self.send_json(JOG.estop())
            elif parsed.path == "/api/jog/diag":
                self.send_json(JOG.diagnose())
            elif parsed.path == "/api/jog/home":
                self.send_json(JOG.home())
            elif parsed.path == "/api/jog/sensor-home":
                request = self.read_json()
                self.send_json(JOG.sensor_home(confirmed=request.get("confirmed", False)))
            elif parsed.path == "/api/jog/go-local-home":
                self.send_json(JOG.go_to_local_home())
            elif parsed.path == "/api/jog/set-local-home":
                request = self.read_json()
                self.send_json(JOG.set_local_home(request.get("x", 0), request.get("y", 0), request.get("z", 0)))
            elif parsed.path == "/api/jog/goto":
                request = self.read_json()
                self.send_json(JOG.goto(request.get("x", 0), request.get("y", 0), request.get("z", 0)))
            elif parsed.path == '/api/jog/ready/save':
                self.send_json(JOG.save_ready_position(self.read_json().get('position')))
            elif parsed.path == '/api/jog/ready/capture':
                self.send_json(JOG.capture_ready_position(self.read_json().get('mode')))
            elif parsed.path == '/api/jog/ready/move':
                request = self.read_json()
                actions = {'xy': JOG.move_to_saved_xy, 'z': JOG.move_to_saved_z, 'xyz': JOG.move_to_saved_xyz}
                if request.get('axes') not in actions:
                    raise ValueError('Ready axes must be xy, z or xyz.')
                self.send_json(actions[request['axes']](request.get('mode')))
            elif parsed.path == "/api/run/start":
                request = self.read_json()
                self.send_json(JOG.run_plan(request.get("segments", []), record_diagnostics=request.get("recordDiagnostics") is True))
            elif parsed.path == "/api/run/stop":
                self.send_json(JOG.run_stop())
            elif parsed.path == "/api/run/resume":
                request = self.read_json()
                self.send_json(JOG.run_resume(request.get("jobId", "")))
            elif parsed.path == "/api/camera/connect":
                request = self.read_json()
                self.send_json(CAMERA.connect(int(request.get("index", 2))))
            elif parsed.path == "/api/camera/disconnect":
                self.send_json(CAMERA.disconnect())
            elif parsed.path == "/api/camera/roi":
                request = self.read_json()
                roi = request.get("roi")
                self.send_json(CAMERA.set_roi(tuple(int(v) for v in roi) if roi else None))
            elif parsed.path == "/api/camera/select-target":
                request = self.read_json()
                self.send_json(CAMERA.select_target(float(request["x"]), float(request["y"])))
            else:
                self.send_error(404)
        except Exception as exc:
            self.send_error_json(400, str(exc))

    def handle_default(self) -> None:
        if DEFAULT_SOURCE.exists():
            params = {
                "fitLongestMm": DEFAULT_LONGEST_SIDE_MM,
                "traceMode": "design",
                "feedRate": DEFAULT_FEED_RATE_MM_S,
                "travelRate": DEFAULT_TRAVEL_RATE_MM_S,
            }
            self.send_json(trace_file(DEFAULT_SOURCE, params))
            return

        self.send_error_json(404, "Sample DXF not found. Upload a DWG/DXF file.")

    def handle_trace(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type},
            )
            params = {key: form.getvalue(key) for key in form.keys() if key != "file"}
            file_item = form["file"] if "file" in form else None
            if file_item is not None and getattr(file_item, "filename", ""):
                UPLOAD_ROOT.mkdir(exist_ok=True)
                safe_name = Path(file_item.filename).name
                source = UPLOAD_ROOT / f"{uuid.uuid4().hex[:8]}_{safe_name}"
                with source.open("wb") as handle:
                    shutil.copyfileobj(file_item.file, handle)
            else:
                source = Path(str(params.get("sourcePath", ""))).expanduser()
        else:
            params = self.read_json()
            source = Path(str(params.get("sourcePath", ""))).expanduser()

        self.send_json(trace_file(source, params))

    def handle_export(self) -> None:
        request = self.read_json()
        session = SESSIONS.get(request.get("sessionId", ""))
        if not session:
            self.send_error_json(404, "Unknown session.")
            return
        plan = build_plan(session, request)
        scheduled_paths = plan.pop("_scheduledPaths")
        pass_by_id = {int(item["id"]): int(item["passes"]) for item in plan["paths"]}
        base_paths: list[LaserPath] = []
        base_passes: list[int] = []
        seen_ids: set[int] = set()
        for path_id, laser_path in zip(plan["scheduledIds"], scheduled_paths):
            if path_id in seen_ids:
                continue
            seen_ids.add(path_id)
            base_paths.append(laser_path)
            base_passes.append(pass_by_id.get(int(path_id), 1))

        uniform_passes = base_passes[0] if base_passes and all(count == base_passes[0] for count in base_passes) else None
        embedded_path_passes = None if uniform_passes is not None else base_passes
        GENERATED_ROOT.mkdir(exist_ok=True)
        stem = "manual_design" if session["metadata"].get("source_type") == "manual" else safe_file_stem(session["sourceName"])
        output = GENERATED_ROOT / f"{stem}_{session['id']}_selected_esp300.py"
        preview = output.with_suffix(".svg")
        metadata = {
            **plan["metadata"],
            "path_count": len(base_paths),
            "scheduled_path_count": sum(base_passes),
            "point_count": sum(len(path.points) for path in base_paths),
            "base_total_length_mm": round(sum(path.length for path in base_paths), 6),
            "total_length_mm": round(sum(path.length * passes for path, passes in zip(base_paths, base_passes)), 6),
        }
        generate_esp300_script(
            base_paths,
            output=output,
            metadata=metadata,
            port=str(request.get("port", "COM5")),
            baudrate=int(request.get("baudrate", 19200)),
            feed_rate=float(metadata.get("feed_rate", DEFAULT_FEED_RATE_MM_S)),
            travel_rate=float(metadata.get("travel_rate", DEFAULT_TRAVEL_RATE_MM_S)),
            passes=uniform_passes,
            position_tolerance=float(request.get("positionTolerance", 0.003)),
            command_settle=float(request.get("commandSettle", DEFAULT_COMMAND_SETTLE_S)),
            dry_run_default=True,
            path_passes=embedded_path_passes,
            z_defocus_mm=float(metadata.get("z_defocus_mm", DEFAULT_Z_DEFOCUS_MM)),
            z_speed=float(metadata.get("z_speed_mm_s", DEFAULT_Z_SPEED_MM_S)),
            wait_mode="position",
        )
        write_preview_svg(base_paths, preview)
        self.send_json(
            {
                "scriptPath": str(output),
                "previewPath": str(preview),
                "fileName": output.name,
                "downloadUrl": f"/api/download?file={quote(output.name)}",
                "plan": plan,
            }
        )

    def handle_download(self, parsed) -> None:
        query = parse_qs(parsed.query)
        file_name = Path(query.get("file", [""])[0]).name
        target = (GENERATED_ROOT / file_name).resolve()
        generated_root = GENERATED_ROOT.resolve()
        if not str(target).startswith(str(generated_root)) or target.suffix != ".py" or not target.exists():
            self.send_error_json(404, "Generated code file not found.")
            return

        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/x-python; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{target.name}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def handle_camera_stream(self) -> None:
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={CAMERA_BOUNDARY}")
        self.end_headers()
        interval = 1.0 / CAMERA_STREAM_FPS
        try:
            while True:
                frame = CAMERA.latest_jpeg()
                if frame is None:
                    time.sleep(0.05)
                    continue
                self.wfile.write(f"--{CAMERA_BOUNDARY}\r\n".encode("ascii"))
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
                time.sleep(interval)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        payload = json.loads(raw or "{}")
        app_audit.emit("http_request_payload", path=self.path, payload=payload)
        return payload

    def send_json(self, payload: dict) -> None:
        app_audit.emit("http_response", path=self.path, status=200, payload=payload)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, status: int, message: str) -> None:
        app_audit.emit("http_error", path=self.path, status=status, error=message)
        data = json.dumps({"error": message}, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args) -> None:
        app_audit.emit("http_access", message=format % args)


def main() -> int:
    app_audit.start(ROOT / "logs" / "app_audit")
    parser = argparse.ArgumentParser(description="Serve the ESP300 motion visualizer.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open-browser", action="store_true", help="Open the UI after the server socket is ready.")
    args = parser.parse_args()

    UPLOAD_ROOT.mkdir(exist_ok=True)
    GENERATED_ROOT.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), VisualizerHandler)
    app_audit.emit("server_ready", host=args.host, port=args.port)
    url = f"http://{args.host}:{server.server_port}"
    print(f"ESP300 WEB SERVER RUNNING: {url}", flush=True)
    print("Keep this window open. Press Ctrl+C to stop the web server.", flush=True)
    if args.open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nESP300 web server stopping...", flush=True)
    finally:
        server.server_close()
        app_audit.emit("server_closed", physical_stop_confirmed=False)
    print("ESP300 web server stopped.", flush=True)
    return 0


app_audit.install_observers(JogController, lambda controller: DEPTH_CONTEXT.observe(controller, JOG_AXES, ESP300_AXIS_SIGNS))
app_audit.install_observers(CameraController, lambda controller: None)

if __name__ == "__main__":
    raise SystemExit(main())

