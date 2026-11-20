"""Signed Y strokes with optional retrace and return to the measured starting Z."""
import math

import app_audit
from esp300_connection import ESP300_AXES, ESP300_AXIS_SIGNS

Z_SPEED_MM_S = 1.0
MAX_REPEAT_COUNT = 10000


def compile_line(pose, length, repeat_count, z_step, speed, depth, round_trip):
    if (isinstance(repeat_count, bool) or not isinstance(repeat_count, int)
            or not 1 <= repeat_count <= MAX_REPEAT_COUNT):
        raise ValueError(f'Repeat count must be an integer within 1–{MAX_REPEAT_COUNT}')
    if not isinstance(round_trip, bool):
        raise ValueError('Round trip must be true or false')
    for value, label in ((length, 'Length'), (depth, 'Depth'), (z_step, 'Z step'), (speed, 'Y speed')):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{label} must be a finite number')
    if abs(length) < 0.001:
        raise ValueError('Length magnitude must be at least 0.001 mm')
    if depth < 0 or 0 < depth < 0.001:
        raise ValueError('Depth must be zero or at least 0.001 mm')
    if z_step < 0 or 0 < z_step < 0.001:
        raise ValueError('Z step must be zero or at least 0.001 mm')
    if not 0.01 <= speed <= 10.0:
        raise ValueError('Y speed must be within 0.01–10 mm/s')
    start = list(pose)
    if len(start) != 3 or not all(math.isfinite(v) for v in start):
        raise ValueError('Invalid measured starting position')
    first_z = start[2] + depth
    segments = []
    current = start

    def append(target, kind, repeat, z_only=False):
        nonlocal current
        velocity = Z_SPEED_MM_S if z_only else speed
        distance = abs(target[2] - current[2]) if z_only else abs(target[1] - current[1])
        segments.append(dict(from3=current, to3=target, speedMmS=velocity,
                             duration=distance / velocity, zOnly=z_only, yOnly=not z_only,
                             lineTest=True, kind=kind, layer='line', pathIndex=repeat))
        current = target

    end_y = start[1] - length
    for repeat in range(1, repeat_count + 1):
        z = first_z + (repeat - 1) * z_step
        if z != current[2]:
            kind = 'line_z_step' if round_trip and repeat > 1 else 'line_z_ingress'
            append([start[0], start[1], z], kind, repeat, True)
        append([start[0], end_y, z], 'line_y_out', repeat)
        if round_trip:
            append([start[0], start[1], z], 'line_y_return', repeat)
        else:
            if z != start[2]:
                append([start[0], end_y, start[2]], 'line_return_z', repeat, True)
            append(list(start), 'line_y_reposition', repeat)
    if current[2] != start[2]:
        append(list(start), 'line_return_z', repeat_count, True)
    return segments


def start_line(jog, body):
    return jog.run_plan([], record_diagnostics=True, line_settings=body)


def prepare_line_locked(jog, body):
    """Capture start and validate the entire route under the job-creation lock."""
    if not jog.connected:
        raise RuntimeError('장비 연결 필요: 자동 연결하지 않습니다')
    if body.get('mode') != ('mock' if jog.dry_run else 'live'):
        raise RuntimeError('화면과 실제 연결 모드가 다릅니다. 연결 상태를 확인하세요')
    jog._require_no_sensor_home_locked()
    jog._require_no_run_locked()
    jog._require_manual_still_locked()
    raw = jog._read_run_pose_locked(check_ready=True)
    pose = [jog._local_of(k, raw[k]) for k in 'xyz']
    segments = compile_line(pose, body.get('length_mm', 1.0),
                            body.get('repeat_count', 1), body.get('z_step_mm', 0.0),
                            body.get('xy_speed', 1.0), body.get('depth_mm', 0.0),
                            body.get('round_trip', False))
    context = jog._run_context_locked()
    for segment in segments:
        segment['lineContext'] = context
        segment['lineAxes'] = (dict(ESP300_AXES), dict(ESP300_AXIS_SIGNS))
    app_audit.emit('line_test_start', segments=segments, start=pose,
                   z_speed_mm_s=Z_SPEED_MM_S, dry_run=jog.dry_run)
    app_audit.RECORDER.checkpoint()
    return segments
