"""Substrate controller hosted by the original application; mock and explicit original-controller execution."""
import threading
from copy import deepcopy
from substrate_engine import Experiment
import app_audit
from substrate_production import upper_right, require_upper_right, set_upper_right, go_upper_right
engine=None
lock=threading.RLock()
last_context=None

def cancel_active():
    if engine:engine.cancel()

def sync_mock(app,jog,context,experiment,worker):
    worker.join()
    with jog._lock:
        current=app['DEPTH_CONTEXT'].observe(jog,app['JOG_AXES'],app['ESP300_AXIS_SIGNS'])
        if jog.connected and jog.dry_run and context==current:
            jog.position=dict(zip('xyz',experiment.cached_position))
            jog.raw_position={k:jog._raw_of(k,v) for k,v in jog.position.items()}


def dispatch(handler, app, action):
    global engine,last_context
    try:
        with lock:
            jog=app['JOG']
            if engine is None:engine=Experiment(app_audit.RECORDER)
            with jog._lock:
                context=app['DEPTH_CONTEXT'].observe(jog,app['JOG_AXES'],app['ESP300_AXIS_SIGNS'])
                pose=[jog.position[k] for k in 'xyz']
                connected=jog.connected;dry=jog.dry_run
                moving=jog._run_state['running'] or jog._sensor_home_state['running']
                reference=upper_right(jog)
            if context!=last_context:
                engine.cancel()
                if engine.worker:engine.worker.join(3)
                engine.context['original_app_context']=deepcopy(context)
                engine.set_home(pose)
                last_context=deepcopy(context)
            if action!='status' and handler.command!='POST':raise RuntimeError('POST required')
            body=handler.read_json() if handler.command=='POST' else {}
            if action in ('set-upper-right','go-upper-right','run','point-run','real-preview','real-start'):
                focus=app['FOCUS'].status()
                if any(focus.get(k) for k in ('active','scanning','surveying')):
                    raise RuntimeError('Autofocus 및 focus scan/survey를 종료한 후 substrate 기준 등록/이동을 실행하세요')
            if action=='status':
                result=engine.snapshot()
                result['original_connection']={'connected':connected,'dry_run':dry}
                blockers=[]
                if not connected:blockers.append('원래 앱에서 장비 연결 필요')
                elif dry:blockers.append('Dry run 상태: 실제 실행은 Live 연결 필요')
                if reference is None:blockers.append('Set upper-right로 substrate 기준 등록 필요')
                result['upper_right']=reference
                if moving:blockers.append('기존 동작 완료 또는 중지 필요')
                result['execution_blockers']=blockers
                result['mode']='live' if connected and not dry else 'mock' if connected else 'disconnected'
                result['hardware_connected']=connected and not dry
                result['live_allowed']=not blockers
                result['blockers']=blockers
                if getattr(engine,'controller_run',False) and jog._run_segments and jog._run_segments[0].get('pointTest'):
                    run=jog.run_status()
                    result['test_type']='point'
                    result['state']={'status':'running' if run['running'] else 'completed' if run.get('done') and not run.get('error') else 'stopped',
                                     'phase':jog._run_segments[min(run['index'],1)]['kind'] if run['running'] else run.get('phase'),
                                     'completed':run['index'],'total':2,'error':run.get('error'),'run_id':run.get('jobId')}
                    result['position']=[jog.position[k] for k in 'xyz']

                if getattr(engine,'controller_run',False) and jog._run_segments and jog._run_segments[0].get('substrateTrial'):
                    run=jog.run_status()
                    result['state']={'status':'running' if run['running'] else 'completed' if run.get('done') and not run.get('error') else 'stopped','phase':run.get('phase'),'completed':min(48,max(0,(run['index']-1)//3)),'site':min(48,max(1,(run['index']+2)//3)),'error':run.get('error'),'run_id':run.get('jobId')}
                    result['position']=[jog.position[k] for k in 'xyz']
            elif action in ('set-upper-right','go-upper-right'):
                if moving or engine.state['status']=='running':raise RuntimeError('이미 동작 중입니다')
                if action=='set-upper-right':
                    result=set_upper_right(jog)
                    engine.controller_run=False
                    engine.set_home(result['upper_right'])
                else:
                    if body.get('mode')!=('mock' if dry else 'live'):raise RuntimeError('화면과 실제 연결 모드가 다릅니다')
                    result=go_upper_right(jog,body.get('xy_speed'))
                    engine.controller_run=True
            elif action=='point-run':
                if moving or engine.state['status']=='running':raise RuntimeError('이미 동작 중입니다')
                from point_test import start_point
                result=start_point(jog,body)
                engine.controller_run=True
            elif action=='run':
                if not connected:raise RuntimeError('장비 연결 필요: 자동 연결하지 않습니다')
                if moving or engine.state['status']=='running':raise RuntimeError('이미 동작 중입니다')
                expected='mock' if dry else 'live'
                if body.get('mode')!=expected:raise RuntimeError('화면과 실제 연결 모드가 다릅니다. 연결 상태를 확인하세요')
                directions={'right':1,'down':1}  # Stage travel: reverse both previous substrate directions.
                with jog._lock: reference=require_upper_right(jog)
                engine.configure(xy_speed=body.get('xy_speed'),origin_xy=reference[:2],reference_xyz=reference,axis_signs=directions)
                token=engine.preview_recipe()['preview_id']
                from substrate_production import compile_trial
                with jog._lock: compile_trial(engine.preview,pose,engine.context['mock_xy_speed_mm_s'],directions,jog,reference)
                if dry:
                    engine.controller_run=False
                    engine.stage.pose=list(pose);engine.stage.origin=list(pose);engine.stage.target=list(pose);engine.stage.duration=0
                    engine.cached_position=list(pose)
                    result=engine.start(token)
                    threading.Thread(target=sync_mock,args=(app,jog,context,engine,engine.worker),daemon=True).start()
                else:
                    from substrate_production import compile_trial,start_trial
                    compile_trial(engine.preview,pose,engine.context['mock_xy_speed_mm_s'],directions,jog,reference)
                    engine.real_review={'preview_id':token,'directions':deepcopy(directions),'pose':list(pose),'reference':reference}
                    result=start_trial(engine,jog,{'preview_id':token,'directions':directions,'confirm_real':True,'beam_exposure_ack':True,'mapping_confirmed':True})
                    engine.controller_run=True
            elif action=='real-preview':
                from substrate_production import compile_trial
                if not engine.validate(body.get('preview_id'))['valid']:raise RuntimeError('Generate current preview first')
                segments=compile_trial(engine.preview,pose,engine.context['mock_xy_speed_mm_s'],body.get('directions',{}),jog,require_upper_right(jog))
                engine.real_review={'preview_id':body['preview_id'],'directions':deepcopy(body['directions']),'pose':list(pose),'reference':reference}
                result={'segments':segments,'warning':'BEAM UNKNOWN / ASSUME ON during ALL retract and XY travel; no laser commands','lens_clearance':'User reports sufficient'}
            elif action=='real-start':
                from substrate_production import start_trial
                result=start_trial(engine,jog,body)
                engine.controller_run=True
            elif action=='config':result=engine.configure(**body)
            elif action=='preview':result=engine.preview_recipe()
            elif action=='validate':result=engine.validate(body.get('preview_id'))
            elif action=='start':
                if not connected or not dry or moving:raise RuntimeError('Connect the original app in Dry run mode and finish other operations first')
                result=engine.start(body.get('preview_id'))
                engine.controller_run=False
                def finish_sync(worker):
                    worker.join()
                    with jog._lock:
                        current=app['DEPTH_CONTEXT'].observe(jog,app['JOG_AXES'],app['ESP300_AXIS_SIGNS'])
                        if jog.dry_run and context==current:
                            jog.position=dict(zip('xyz',engine.cached_position))
                            jog.raw_position={k:jog._raw_of(k,v) for k,v in jog.position.items()}
                threading.Thread(target=finish_sync,args=(engine.worker,),daemon=True).start()
            elif action in ('cancel','shutdown'):
                result=engine.cancel()
                if jog._run_state.get('running') and any(s.get('substrateTrial') for s in jog._run_segments):jog.run_stop()
            else:raise RuntimeError('Unknown substrate action; use original app controls.')
            # Synchronize synthetic positions to the original display only during mock trial.
            if connected and dry and engine.state['status']=='running':
                with jog._lock:
                    jog.position=dict(zip('xyz',engine.cached_position))
                    jog.raw_position={k:jog._raw_of(k,v) for k,v in jog.position.items()}
            handler.send_json(result)
    except Exception as exc:handler.send_error_json(400,str(exc))
