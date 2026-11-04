"""Single-point Z ingress and fixed-speed return using the existing run worker."""
import math

import app_audit
from esp300_connection import ESP300_AXES, ESP300_AXIS_SIGNS

DEFAULT_DEPTH_MM = 3.0
DEFAULT_INGRESS_MM_S = 0.01
RETURN_MM_S = 1.0


def compile_point(pose, depth, speed, jog):
    for value, label in ((depth, 'Depth'), (speed, 'Ingress speed')):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'{label} must be a finite number')
    if depth <= 0:
        raise ValueError('Depth must be greater than zero')
    # Match the existing run worker minimum; never silently accelerate ingress.
    if not 0.01 <= speed <= 10.0:
        raise ValueError('Ingress speed must be within 0.01–10 mm/s')
    start = list(pose)
    if len(start) != 3 or not all(math.isfinite(v) for v in start):
        raise ValueError('Invalid measured starting position')
    bottom = [start[0], start[1], start[2] + depth]
    for target in (start, bottom):
        if not all(math.isfinite(v) for v in target):
            raise ValueError('Invalid point target')
        if math.hypot(target[0] - jog.limit_center[0], target[1] - jog.limit_center[1]) > jog.limit_radius:
            raise ValueError('Point exceeds existing XY limit')
        if abs(target[2] - jog.home_ref['z']) > jog.z_range:
            raise ValueError('Point exceeds existing Z limit')
    return [dict(from3=origin, to3=target, speedMmS=velocity,
                 duration=depth / velocity, zOnly=True, pointTest=True,
                 kind=kind, layer='point', pathIndex=1)
            for origin, target, velocity, kind in
            ((start, bottom, speed, 'point_ingress'),
             (bottom, start, RETURN_MM_S, 'point_return'))]


def start_point(jog, body):
    return jog.run_plan([], record_diagnostics=True, point_settings=body)


def prepare_point_locked(jog, body):
    """Called with the run worker's lock held, through job creation."""
    if not jog.connected:
        raise RuntimeError('장비 연결 필요: 자동 연결하지 않습니다')
    if body.get('mode') != ('mock' if jog.dry_run else 'live'):
        raise RuntimeError('화면과 실제 연결 모드가 다릅니다. 연결 상태를 확인하세요')
    jog._require_no_sensor_home_locked()
    jog._require_no_run_locked()
    jog._require_manual_still_locked()
    raw = jog._read_run_pose_locked(check_ready=True)
    pose = [jog._local_of(k, raw[k]) for k in 'xyz']
    segments = compile_point(pose, body.get('depth_mm', DEFAULT_DEPTH_MM),
                             body.get('ingress_speed', DEFAULT_INGRESS_MM_S), jog)
    for segment in segments:
        segment['pointContext'] = jog._run_context_locked()
        segment['pointAxes'] = (dict(ESP300_AXES), dict(ESP300_AXIS_SIGNS))
    app_audit.emit('point_test_start', segments=segments, start=pose,
                   return_speed_mm_s=RETURN_MM_S, dry_run=jog.dry_run)
    app_audit.RECORDER.checkpoint()
    return segments
