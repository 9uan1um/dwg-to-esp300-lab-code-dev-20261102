"""Interactive MOCK substrate workflow. No serial/network/device imports or live adapter."""
from __future__ import annotations
from copy import deepcopy
import math
import threading
import time
import uuid
from depth_recipe import build_recipe, default_context, validate_recipe

BLOCKERS = ['Physical right/down axis mapping is unverified',
            'Lens, sample and support clearance is unverified',
            'Reliable beam blocking/control and preflight are unverified',
            'Continuous beam traversal may modify material',
            'No live transport or motor-enable implementation is supplied']

def finite(value, name):
    if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
        raise ValueError(name+' must be a finite number')
    return float(value)

def position(value):
    if not isinstance(value,(list,tuple)) or len(value)!=3:raise ValueError('Empty or malformed simulated TP position')
    out=[finite(v,'Position') for v in value]
    if any(abs(v)>1000 for v in out):raise ValueError('Invalid mock position magnitude (not a physical safety limit)')
    return out

class MockStage:
    mode='mock'
    def __init__(self, playback=20, fault='none'):
        self.pose=[0.,0.,-.5]
        self.origin=list(self.pose);self.target=list(self.pose)
        self.started=0.;self.duration=0.
        self.playback=playback;self.fault=fault;self.intents=[]
    def read_position(self):
        if self.fault=='empty':return ''
        if self.fault=='invalid':return [float('nan'),0,0]
        if self.fault=='timeout':return list(self.origin)
        progress=min(1.,(time.monotonic()-self.started)/self.duration) if self.duration else 1.
        self.pose=[a+(b-a)*progress for a,b in zip(self.origin,self.target)]
        return list(self.pose)
    def move(self,target,speed):
        self.origin=position(self.read_position());self.target=position(target)
        self.duration=math.dist(self.origin,self.target)/speed/self.playback
        self.started=time.monotonic()
        self.intents.append({'target':list(target),'requested_speed_mm_s':speed,'device_bytes_sent':None})
    def stop(self):
        # Stop only this in-memory model. No device command can be emitted.
        if self.fault=='none':self.pose=position(self.read_position())
        self.target=list(self.pose);self.origin=list(self.pose);self.duration=0

class Cancelled(Exception):pass

class Experiment:
    def __init__(self, audit, stage=None):
        self.audit=audit;self.stage=stage or MockStage()
        if type(self.stage) is not MockStage:raise ValueError('Only the in-memory MockStage is permitted')
        self.lock=threading.RLock();self.cancel_event=threading.Event();self.worker=None
        self.context={**default_context(),'session':uuid.uuid4().hex,'mode':'mock',
                      'mock_home':[0.,0.,0.],'mock_xy_speed_mm_s':None,'playback':20.,'fault':'none'}
        self.preview=None;self.preview_id=None
        self.state={'status':'idle','phase':'idle','completed':0,'site':None,'error':None,'run_id':None}
        self.cached_position=list(self.stage.pose);self.previous_sample=None;self.last_cancel_reason=None
        self.audit.emit('mock_session_ready',mode='mock',hardware_connected=False,blockers=BLOCKERS)
        self.audit.checkpoint()

    def _healthy(self):self.audit.checkpoint()
    def _idle(self):
        if self.worker and self.worker.is_alive():raise RuntimeError('A mock operation is active; cancel and wait first')
    def _invalidate(self, reason):
        self.context['origin_revision']+=1;self.preview=None;self.preview_id=None;self.previous_sample=None
        self.audit.emit('mock_context_changed',reason=reason,context=self.context,recipe_invalidated=True)
    def configure(self, **values):
        allowed={'xy_speed','playback','fault','axis_signs','origin_xy','reference_xyz'}
        if set(values)-allowed:raise ValueError('Unknown configuration field')
        with self.lock:
            updated=deepcopy(self.context)
            if 'reference_xyz' in values:
                updated['substrate_origin_mm']=position(values['reference_xyz'])
            if 'origin_xy' in values:
                xy=values['origin_xy']
                if not isinstance(xy,list) or len(xy)!=2:raise ValueError('Origin requires X,Y')
                updated['planning_origin_mm']=[finite(v,'Origin') for v in xy]
            if 'xy_speed' in values:
                n=finite(values['xy_speed'],'Mock XY traverse speed')
                if not 0<n<=10:raise ValueError('Mock XY speed must be >0 and <=10 mm/s')
                updated['mock_xy_speed_mm_s']=n
            if 'playback' in values:
                n=finite(values['playback'],'Playback')
                if not 1<=n<=1000:raise ValueError('Playback must be 1–1000×')
                updated['playback']=n
            if 'fault' in values:
                if values['fault'] not in ('none','empty','invalid','timeout'):raise ValueError('Unknown mock fault')
                updated['fault']=values['fault']
            if 'axis_signs' in values:
                signs=values['axis_signs']
                if not isinstance(signs,dict) or set(signs)!={'right','down'} or any(type(v) is not int or v not in (-1,1) for v in signs.values()):raise ValueError('Mock signs require right/down ±1')
                updated['mock_axis_signs']=dict(signs)  # never marks physical mapping verified
            self._healthy()
            # Context changes cancel active work before the next model command.
            if self.worker and self.worker.is_alive():self.cancel_event.set();self.last_cancel_reason='Configuration changed'
            self.context=updated;self._invalidate('configuration');return self.snapshot()

    def set_home(self, xyz):
        xyz=position(xyz)
        with self.lock:
            self._healthy()
            if self.worker and self.worker.is_alive():self.cancel_event.set();self.last_cancel_reason='Origin changed'
            self.stage.stop()
            self.stage.pose=list(xyz);self.stage.origin=list(xyz);self.stage.target=list(xyz);self.stage.duration=0
            self.cached_position=list(xyz)
            self.context['mock_home']=xyz;self.context['local_offset']={k:v for k,v in zip('xyz',xyz)}
            self._invalidate('set_local_home');return self.snapshot()

    def preview_recipe(self):
        with self.lock:
            self._idle();self._healthy()
            self.preview=build_recipe(self.context);self.preview_id=uuid.uuid4().hex
            self.audit.emit('recipe_preview',preview_id=self.preview_id,recipe=self.preview)
            self._healthy();return {'preview_id':self.preview_id,'recipe':deepcopy(self.preview)}

    def validate(self, preview_id):
        with self.lock:
            valid=bool(self.preview and preview_id==self.preview_id and validate_recipe(self.preview,self.context)['valid'])
            return {'valid':valid,'hardware_executable':False,'simulation_only':True}

    def start(self, preview_id):
        with self.lock:
            self._idle();self._healthy()
            if not self.validate(preview_id)['valid']:raise RuntimeError('Preview missing, consumed or stale; regenerate')
            if self.context['mock_xy_speed_mm_s'] is None:raise RuntimeError('Specify a simulation-only XY traverse speed first')
            recipe=deepcopy(self.preview);context=deepcopy(self.context)
            self.preview=None;self.preview_id=None  # one-shot token blocks duplicate starts/replay
            self.cancel_event.clear();self.last_cancel_reason=None;self.previous_sample=None
            self.stage.playback=context['playback'];self.stage.fault=context['fault']
            self.state={'status':'running','phase':'starting','completed':0,'site':None,'error':None,'run_id':uuid.uuid4().hex}
            self.audit.emit('mock_run_started',run_id=self.state['run_id'],recipe=recipe,context=context)
            self.worker=threading.Thread(target=self._run,args=(recipe,context),name='substrate-mock-run',daemon=True)
            self.worker.start();return self.snapshot()

    def _check(self, context):
        if self.cancel_event.is_set():raise Cancelled(self.last_cancel_reason or 'User cancelled')
        if context!=self.context:raise Cancelled('Origin or configuration changed')
        self._healthy()

    def _move(self,target,speed,phase,context,site=None):
        speed=finite(speed,'Speed')
        if speed<=0:raise ValueError('Speed must be positive')
        with self.lock:
            self._check(context);self.state.update(phase=phase,site=site)
            self.audit.emit('mock_move_intent',run_id=self.state['run_id'],phase=phase,site=site,target=target,
                            requested_speed_mm_s=speed,device_bytes_sent=None,beam='assumed continuously on; material effect unverified')
            self._healthy();self.stage.move(target,speed)
            deadline=time.monotonic()+max(.25,self.stage.duration*2+.25)
        while True:
            with self.lock:
                self._check(context)
                sample=position(self.stage.read_position());now=time.monotonic()
                previous=self.previous_sample
                estimate=[(v-previous[1][k])/(now-previous[0]) for k,v in enumerate(sample)] if previous and now>previous[0] else None
                self.previous_sample=(now,list(sample));self.cached_position=list(sample)
                self.audit.emit('mock_position_sample',position_mm=sample,estimated_host_time_average_mm_s=estimate,
                                meaning='Synthetic positions / host interval at accelerated playback; NOT real velocity feedback',
                                playback=context['playback'],phase=phase,site=site)
                if math.dist(sample,target)<=1e-7:
                    self._healthy();return
                if time.monotonic()>=deadline:raise TimeoutError('Simulated TP arrival timed out')
            self.cancel_event.wait(.01)

    def _run(self,recipe,context):
        outcome='completed';error=None
        try:
            rx,ry,rz=context.get('substrate_origin_mm',[0.,0.,0.])
            # Establish the modeled return plane before XY changes; not a claim of safe clearance.
            self._move([self.cached_position[0],self.cached_position[1],rz-.5],1.2,'initial_return',context)
            for site in recipe['sites']:
                ox,oy=context.get('planning_origin_mm',[0.,0.])
                signs=context.get('mock_axis_signs',{'right':1,'down':1})
                x=ox+signs['right']*(site['logical_right_mm']-ox)
                y=oy+signs['down']*(site['logical_down_mm']-oy);n=site['site']
                self._move([x,y,rz-.5],context['mock_xy_speed_mm_s'],'xy_traverse',context,n)
                self._move([x,y,rz+site['target_relative_stage_z_mm']],site['ingress']['requested_speed_mm_s'],'ingress',context,n)
                self._move([x,y,rz-.5],1.2,'return',context,n)
                with self.lock:self.state['completed']=n
            with self.lock:self.state['phase']='completion_dwell'
            self.audit.emit('mock_completion_dwell_start',seconds=3.0)
            deadline=time.monotonic()+3.0
            while time.monotonic()<deadline:
                if self.cancel_event.wait(min(.05,max(0,deadline-time.monotonic()))):raise Cancelled('Cancelled during completion wait')
                self._healthy()
            self.audit.emit('mock_completion_dwell_complete',seconds=3.0)
            self._move([rx,ry,rz-.5],context['mock_xy_speed_mm_s'],'home_xy',context,48)
            self._move([rx,ry,rz],1.2,'home_z',context,48)
        except Cancelled as exc:outcome='cancelled';error=str(exc)
        except Exception as exc:outcome='failed';error=type(exc).__name__+': '+str(exc)
        finally:
            with self.lock:
                self.stage.stop()
                self.state.update(status=outcome,phase=outcome,error=error)
                self.audit.emit('mock_run_finished',**self.state,hardware_operation_performed=False)
                try:self._healthy()
                except Exception as exc:self.state.update(status='failed',phase='failed',error='Audit failure: '+str(exc))

    def cancel(self):
        # Cancellation remains available even when logging fails.
        with self.lock:
            self.last_cancel_reason='User cancelled';self.cancel_event.set()
            self.audit.emit('mock_cancel_requested',run_id=self.state['run_id'])
            return self.snapshot()

    def manual(self,action,axis=None,delta=None):
        with self.lock:
            self._idle();self._healthy()
            self.audit.emit('mock_manual_intent',action=action,axis=axis,delta=delta)
            if action=='center':self.stage.pose=[0.,0.,-.5];self._invalidate('simulated center sensor')
            elif action=='jog':
                if axis not in ('x','y','z'):raise ValueError('Choose x/y/z')
                delta=finite(delta,'Jog delta')
                if abs(delta)>5:raise ValueError('Mock jog step maximum 5 mm')
                self.stage.pose['xyz'.index(axis)]+=delta;self.stage.pose=position(self.stage.pose)
            else:raise ValueError('Unknown mock manual action')
            self.stage.origin=list(self.stage.pose);self.stage.target=list(self.stage.pose);self.stage.duration=0
            self.cached_position=list(self.stage.pose)
            self.audit.emit('mock_manual_result',action=action,position=self.cached_position)
            self._healthy();return self.snapshot()

    def snapshot(self):
        with self.lock:
            return {'mode':'mock','hardware_connected':False,'motors_enabled':False,'live_allowed':False,
                    'blockers':list(BLOCKERS),'state':deepcopy(self.state),'position':list(self.cached_position),
                    'context':deepcopy(self.context),'preview_id':self.preview_id,'audit':self.audit.health()}

    def close(self):
        self.cancel()
        if self.worker:self.worker.join(5)
        if self.worker and self.worker.is_alive():raise RuntimeError('Mock worker did not terminate')
        self.audit.emit('mock_session_closed')

def live_connect(*args,**kwargs):raise RuntimeError('Live connection is disabled: '+'; '.join(BLOCKERS))
def enable_motors(*args,**kwargs):raise RuntimeError('Motor enabling is a separate operation and is disabled')
