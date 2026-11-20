"""Server-side trial compilation into the existing JogController run mechanism."""
import math
import app_audit
from z_limit import check_z_target
from esp300_connection import ESP300_AXES, ESP300_AXIS_SIGNS

def reference_context(jog):
    return (jog._run_context_locked(), jog.z_home_raw, jog.dry_run, jog.port,
            jog.baudrate, dict(ESP300_AXES), dict(ESP300_AXIS_SIGNS))


def upper_right(jog):
    ref = getattr(jog, '_substrate_upper_right', None)
    current = reference_context(jog)
    if jog.connected and ref and ref['context'] != current and 'raw' in ref:
        # Z focus trim changes the local coordinate frame during ordinary jog.
        # Keep the registered physical point, rather than losing it or shifting it
        # with the focus offset. All other context changes still invalidate it.
        previous = ref['context']
        offsets = dict(current[0][1])
        old_offsets = dict(previous[0][1])
        delta = offsets['z'] - old_offsets['z']
        offsets['z'] = old_offsets['z']
        normalized_run = (current[0][0], tuple(offsets.items()), *current[0][2:])
        normalized = (normalized_run, *current[1:])
        trim_delta = jog.focus_trim_mm - ref['focus_trim_mm']
        if normalized == previous and math.isclose(delta, trim_delta, abs_tol=1e-9):
            ref['pose'] = [jog._local_of(k, ref['raw'][k]) for k in 'xyz']
            ref['context'] = current
            ref['focus_trim_mm'] = jog.focus_trim_mm
            app_audit.emit('substrate_upper_right_rebased', pose=ref['pose'], raw=ref['raw'], focus_trim_mm=jog.focus_trim_mm)
    if not jog.connected or not ref or ref['context'] != current:
        jog._substrate_upper_right = None
        return None
    return list(ref['pose'])


def require_upper_right(jog):
    ref = upper_right(jog)
    if ref is None:
        raise RuntimeError('Set upper-right로 substrate 우측 상단·초점 기준을 먼저 등록하세요')
    return ref


def set_upper_right(jog):
    with jog._lock:
        jog._require_no_sensor_home_locked(); jog._require_no_run_locked(); jog._require_manual_still_locked()
        if not jog.connected: raise RuntimeError('장비 연결 필요')
        raw = jog._read_run_pose_locked()
        pose = [jog._local_of(k, raw[k]) for k in 'xyz']
        if not all(math.isfinite(v) for v in pose): raise ValueError('Invalid measured position')
        app_audit.emit('substrate_upper_right_set', pose=pose, raw=raw, context=reference_context(jog))
        app_audit.RECORDER.checkpoint()
        jog._substrate_upper_right = {'pose': pose, 'raw': dict(raw),
                                     'focus_trim_mm': jog.focus_trim_mm,
                                     'context': reference_context(jog)}
        return {'upper_right': pose, 'motion_started': False}


def compile_trial(recipe, pose, xy_speed, directions, controller, reference=None):
    if set(directions)!={'right','down'} or any(type(v) is not int or v not in (-1,1) for v in directions.values()):raise ValueError('Confirm right/down local-axis signs explicitly')
    if not isinstance(xy_speed,(int,float)) or isinstance(xy_speed,bool) or not math.isfinite(xy_speed) or not .01<=xy_speed<=10:raise ValueError('XY speed must be explicitly set within 0.01–10 mm/s')
    current=list(pose)
    if len(current)!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in current):raise ValueError('Invalid measured starting position')
    segments=[];ox,oy=recipe['context'].get('planning_origin_mm',[0,0])
    rx,ry,rz = reference if reference is not None else (ox,oy,0.)
    def add(target,speed,kind,site,zonly):
        nonlocal current
        if not all(math.isfinite(v) for v in target):raise ValueError('Nonfinite target')
        if zonly:
            check_z_target(controller._raw_of("z", target[2]), controller.z_max_mm)
        distance=math.dist(current,target)
        segments.append({'from3':current,'to3':list(target),'speedMmS':speed,'duration':max(distance/speed,.001),'zOnly':zonly,'kind':kind,'pathIndex':site,'layer':'substrate','substrateTrial':True,'beamState':'unknown; assume continuous exposure'})
        current=list(target)
    add([current[0],current[1],rz-.5],1.2,'substrate_initial_return',0,True)
    for s in recipe['sites']:
        x=rx+directions['right']*(s['logical_right_mm']-ox);y=ry+directions['down']*(s['logical_down_mm']-oy)
        add([x,y,rz-.5],xy_speed,'substrate_transit',s['site'],False)
        add([x,y,rz+s['target_relative_stage_z_mm']],s['ingress']['requested_speed_mm_s'],'substrate_ingress',s['site'],True)
        add([x,y,rz-.5],1.2,'substrate_return',s['site'],True)
    add(current,1.2,'substrate_completion_dwell',48,True)
    segments[-1]['dwellSeconds']=3.0
    segments[-1]['duration']=3.0
    add([rx,ry,rz-.5],xy_speed,'substrate_home_xy',48,False)
    add([rx,ry,rz],1.2,'substrate_home_z',48,True)
    return segments

def start_trial(engine,jog,body):
    if body.get('confirm_real') is not True or body.get('beam_exposure_ack') is not True or body.get('mapping_confirmed') is not True:
        raise RuntimeError('Explicit REAL execution, beam-on exposure and mapping confirmations required')
    if not engine.validate(body.get('preview_id'))['valid']:raise RuntimeError('Preview stale, missing or consumed')
    review=getattr(engine,'real_review',None)
    if not review or review['preview_id']!=body.get('preview_id') or review['directions']!=body.get('directions'):
        raise RuntimeError('Review the direction-mapped REAL path before confirming execution')
    with jog._lock:
        if not jog.connected or jog.dry_run:raise RuntimeError('Select and connect LIVE in the original app first')
        jog._require_no_sensor_home_locked();jog._require_no_run_locked();jog._require_manual_still_locked()
        reference=require_upper_right(jog)
        if review.get('reference') != reference: raise RuntimeError('Upper-right changed; review again')
        raw=jog._read_run_pose_locked(check_ready=True)
        pose=[jog._local_of(k,raw[k]) for k in 'xyz']
        if math.dist(pose,review['pose'])>.01:raise RuntimeError('Position changed since REAL review; review again')
        segments=compile_trial(engine.preview,pose,engine.context['mock_xy_speed_mm_s'],body.get('directions',{}),jog,reference)
        for k,v in zip('xyz',pose):jog.position[k]=v;jog.raw_position[k]=raw[k]
        context=jog._run_context_locked()
    app_audit.emit('substrate_real_preflight',segments=segments,confirmations=body,lens_clearance='user reports sufficient; not machine-verified',beam='unknown; assume on')
    app_audit.RECORDER.checkpoint()
    # Consume before starting to prevent double-click replay, including a failed start.
    engine.preview=None;engine.preview_id=None
    engine.real_review=None
    for segment in segments:
        segment['substrateContext']=context
        segment['substrateAxes']=(dict(ESP300_AXES),dict(ESP300_AXIS_SIGNS))
    return jog.run_plan(segments,record_diagnostics=True)


def go_upper_right(jog, xy_speed):
    with jog._lock:
        jog._require_no_sensor_home_locked(); jog._require_no_run_locked(); jog._require_manual_still_locked()
        ref = require_upper_right(jog)
        raw = jog._read_run_pose_locked(check_ready=True)
        pose = [jog._local_of(k,raw[k]) for k in 'xyz']
        # Reuse all limit/speed validation, with no experiment sites or dwell.
        segments = compile_trial({'context': {}, 'sites': []},pose,xy_speed,
                                 {'right':1,'down':1},jog,ref)
        segments = [s for s in segments if s['kind'] != 'substrate_completion_dwell']
        context = jog._run_context_locked()
        for s in segments:
            s['substrateContext'] = context
            s['substrateAxes'] = (dict(ESP300_AXES),dict(ESP300_AXIS_SIGNS))
        app_audit.emit('substrate_go_upper_right', reference=ref, segments=segments)
        app_audit.RECORDER.checkpoint()
    return jog.run_plan(segments,record_diagnostics=True)
