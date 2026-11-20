"""Current-position XY circle, one focus offset, and return to measured start.

Uses the existing point-to-point worker (180 chords/revolution), not controller
arc interpolation. Z is stage displacement, not optical depth in the sample.
"""
import math

import app_audit
from esp300_connection import ESP300_AXES, ESP300_AXIS_SIGNS

SEGMENTS_PER_TURN = 180
MAX_REPEAT_COUNT = 1000
Z_SPEED_MM_S = 1.0


def compile_circle(pose, radius, speed, repeat_count, focus_offset, jog):
    if (isinstance(repeat_count, bool) or not isinstance(repeat_count, int)
            or not 1 <= repeat_count <= MAX_REPEAT_COUNT):
        raise ValueError(f'Repeat count must be an integer within 1–{MAX_REPEAT_COUNT}')
    for value, label in ((radius, 'Radius'), (speed, 'XY speed'), (focus_offset, 'Focus Z offset')):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{label} must be a finite number')
    if radius < 0.001:
        raise ValueError('Radius must be at least 0.001 mm')
    if not 0.01 <= speed <= 10.0:
        raise ValueError('XY speed must be within 0.01–10 mm/s')
    if focus_offset < 0 or 0 < focus_offset < 0.001:
        raise ValueError('Focus Z offset must be zero or at least 0.001 mm')
    start = list(pose)
    if len(start) != 3 or not all(math.isfinite(v) for v in start):
        raise ValueError('Invalid measured starting position')
    x, y, z = start
    focus_z = z + focus_offset
    if not all(math.isfinite(v) for v in (x + radius, x - radius, y + radius, y - radius, focus_z)):
        raise ValueError('Invalid circle target')
    segments = []
    current = start

    def append(target, kind, repeat=0, z_only=False):
        nonlocal current
        velocity = Z_SPEED_MM_S if z_only else speed
        segments.append(dict(from3=current, to3=target, speedMmS=velocity,
                             duration=math.dist(current, target) / velocity,
                             zOnly=z_only, circleTest=True, kind=kind,
                             layer='circle', pathIndex=repeat))
        current = target

    # Position off focus before entering, so no radius is traversed at focus
    # when a positive focus offset was supplied. No shutter control is implied.
    append([x + radius, y, z], 'circle_position')
    if focus_offset:
        append([x + radius, y, focus_z], 'circle_focus', z_only=True)
    for repeat in range(1, repeat_count + 1):
        for step in range(1, SEGMENTS_PER_TURN + 1):
            angle = math.tau * step / SEGMENTS_PER_TURN
            target = ([x + radius, y, focus_z] if step == SEGMENTS_PER_TURN else
                      [x + radius * math.cos(angle), y + radius * math.sin(angle), focus_z])
            append(target, 'circle_trace', repeat)
    if focus_offset:
        append([x + radius, y, z], 'circle_retract', repeat_count, True)
    append(list(start), 'circle_center', repeat_count)
    return segments


def start_circle(jog, body):
    return jog.run_plan([], record_diagnostics=True, circle_settings=body)


def prepare_circle_locked(jog, body):
    """Measure and freeze the entire route under the job-creation lock."""
    if not jog.connected:
        raise RuntimeError('장비 연결 필요: 자동 연결하지 않습니다')
    if body.get('mode') != ('mock' if jog.dry_run else 'live'):
        raise RuntimeError('화면과 실제 연결 모드가 다릅니다. 연결 상태를 확인하세요')
    jog._require_no_sensor_home_locked()
    jog._require_no_run_locked()
    jog._require_manual_still_locked()
    raw = jog._read_run_pose_locked(check_ready=True)
    pose = [jog._local_of(k, raw[k]) for k in 'xyz']
    segments = compile_circle(pose, body.get('radius_mm', 1.0), body.get('xy_speed', 1.0),
                              body.get('repeat_count', 1), body.get('focus_offset_mm', 0.0), jog)
    context = jog._run_context_locked()
    for segment in segments:
        segment['circleContext'] = context
        segment['circleAxes'] = (dict(ESP300_AXES), dict(ESP300_AXIS_SIGNS))
    app_audit.emit('circle_test_start', start=pose, settings=body,
                   segment_count=len(segments), segments_per_turn=SEGMENTS_PER_TURN,
                   z_speed_mm_s=Z_SPEED_MM_S, dry_run=jog.dry_run)
    app_audit.RECORDER.checkpoint()
    return segments
