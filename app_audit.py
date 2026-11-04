"""Passive asynchronous JSONL audit. Never opens hardware or replays commands."""
from __future__ import annotations
import atexit
import functools
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import queue
import sys
import threading
import time
import uuid
from datetime import datetime, timezone

def clean(value):
    if value is None or isinstance(value, (str, bool, int)): return value
    if isinstance(value, float): return value if math.isfinite(value) else str(value)
    if isinstance(value, dict): return {str(k): clean(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    return '<'+type(value).__name__+'>'

class Recorder:
    def __enter__(self): return self
    def __exit__(self,*args): self.close()
    def __init__(self, directory, capacity=10000):
        self.session = uuid.uuid4().hex
        self.path = Path(directory) / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+self.session+'.jsonl')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stream = self.path.open('xb', buffering=0)
        self.q = queue.Queue(capacity)
        self.lock = threading.RLock()
        self.seq = 0
        self.dropped = 0
        self.error = None
        self.closed = False
        self.durable_seq = 0
        self.previous_samples = {}
        self.worker = threading.Thread(target=self._worker, name='app-audit-writer', daemon=True)
        self.worker.start()
        self.emit('app_start', pid=os.getpid(), executable=sys.executable, coverage='application Python process; not browser or launcher')

    def emit(self, event, **details):
        # Audit errors never substitute for the original operation's result.
        try:
            with self.lock:
                if self.closed: return
                self.seq += 1
                record = {'seq': self.seq, 'session': self.session,
                          'utc': datetime.now(timezone.utc).isoformat(), 'monotonic_ns': time.monotonic_ns(),
                          'thread': threading.current_thread().name, 'event': event, 'details': clean(details)}
                self.q.put_nowait(record)
        except queue.Full:
            self.dropped += 1
            if self.dropped == 1: print('AUDIT WARNING: queue full; events are being lost', file=sys.stderr)
        except Exception as exc:
            self.error = repr(exc)

    def _worker(self):
        previous = '0'*64
        try:
            while True:
                item = self.q.get()
                try:
                    if item is None: return
                    item['previous_sha256'] = previous
                    payload = json.dumps(item, sort_keys=True, allow_nan=False, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
                    previous = hashlib.sha256(payload).hexdigest()
                    data = json.dumps({'record': item, 'sha256': previous}, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
                    view = memoryview(data)
                    while view:
                        n = self.stream.write(view)
                        if not n: raise OSError('Short audit write')
                        view = view[n:]
                    os.fsync(self.stream.fileno())
                    self.durable_seq = item['seq']
                finally:
                    self.q.task_done()
        except Exception as exc:
            self.error = repr(exc)
            print('AUDIT WRITE FAILED: '+self.error, file=sys.stderr)

    def reset_samples(self):
        with self.lock:self.previous_samples.clear()

    def position(self, axis, value, *, simulated=False, generation=None, reference_transition=False):
        now = time.monotonic_ns()
        with self.lock:
            key=(generation, axis, simulated)
            prior=None if reference_transition else self.previous_samples.get(key)
            if reference_transition:self.previous_samples.pop(key,None)
            else:self.previous_samples[key]=(now,value)
        dt = (now-prior[0])/1e9 if prior else None
        estimate = (value-prior[1])/dt if prior and dt and dt>0 else None
        self.emit('position_sample', axis=axis, controller_raw_mm=value, sampled_monotonic_ns=now,
                  simulated=simulated, reference_transition=reference_transition, interval_s=dt, estimated_average_mm_s=estimate,
                  velocity_meaning='delta position / host read interval; not true instantaneous velocity', generation=generation)

    def health(self):
        return {'path':str(self.path), 'session':self.session, 'dropped_events':self.dropped,
                'write_error':self.error, 'queued_events':self.q.qsize(), 'closed':self.closed,
                'durable_seq':self.durable_seq, 'writer_alive':self.worker.is_alive()}

    def checkpoint(self, timeout=2):
        """New mock workflow requires durable evidence before advancing; never wait forever."""
        with self.lock:target=self.seq
        deadline=time.monotonic()+timeout
        while True:
            if self.error or self.dropped or self.closed or not self.worker.is_alive():
                raise RuntimeError('Audit unavailable: '+str(self.health()))
            if self.durable_seq>=target:return
            if time.monotonic()>=deadline:raise RuntimeError('Audit durability timeout')
            time.sleep(.002)

    def close(self):
        with self.lock:
            if self.closed: return
            self.emit('app_exit', dropped_events=self.dropped, write_error=self.error,
                      outcome='normal Python shutdown; does not confirm physical stop')
            self.closed=True
        try: self.q.put(None, timeout=2)
        except queue.Full: self.error='Shutdown queue timeout'
        self.worker.join(5)
        if self.worker.is_alive():
            self.error='Shutdown drain timeout; audit tail may be incomplete'
            print(self.error, file=sys.stderr)
        else: self.stream.close()

def validate_log(path):
    """Read only. Preserve partial/corrupt tail for forensic inspection."""
    previous='0'*64
    count=0
    last_seq=0
    gaps=[]
    last_event=None
    error=None
    with Path(path).open('rb') as stream:
        for line in stream:
            try:
                if not line.endswith(b'\n'): raise ValueError('Incomplete tail')
                entry=json.loads(line)
                rec=entry['record']
                payload=json.dumps(rec,sort_keys=True,allow_nan=False,ensure_ascii=False,separators=(',', ':')).encode('utf-8')
                if rec['previous_sha256']!=previous or hashlib.sha256(payload).hexdigest()!=entry['sha256']:
                    raise ValueError('Checksum/chain mismatch')
                if rec['seq']!=last_seq+1:gaps.append([last_seq+1,rec['seq']-1])
                previous=entry['sha256'];last_seq=rec['seq'];count+=1;last_event=rec['event']
            except Exception as exc:
                error=str(exc);break
    return {'valid_prefix_records':count,'error':error,'sequence_gaps':gaps,
            'clean_exit':last_event=='app_exit' and error is None, 'last_event':last_event}

class NullRecorder:
    def emit(self,*args,**kwargs): pass
    def position(self,*args,**kwargs): pass
    def reset_samples(self):pass
    def health(self):return {'active':False}
    def close(self):pass

RECORDER=NullRecorder()

def start(directory):
    global RECORDER
    if not isinstance(RECORDER,NullRecorder):return RECORDER
    RECORDER=Recorder(directory)
    atexit.register(RECORDER.close)
    old=sys.excepthook
    def uncaught(kind,value,tb):
        RECORDER.emit('uncaught_error',type=kind.__name__,error=str(value));old(kind,value,tb)
    sys.excepthook=uncaught
    old_thread=threading.excepthook
    def thread_error(args):
        RECORDER.emit('thread_uncaught_error',type=args.exc_type.__name__,error=str(args.exc_value));old_thread(args)
    threading.excepthook=thread_error
    return RECORDER

def emit(event, **details): RECORDER.emit(event,**details)

def install_observers(controller_class, context_callback):
    """Wrap intentions/results; original calls, arguments, returns and exceptions retained."""
    for name, method in list(vars(controller_class).items()):
        if not callable(method) or name.startswith('__') or getattr(method,'_audited',False):continue
        if name.startswith('_') and not (name.endswith('_worker') or name.endswith('_loop') or name in {'_worker','_write','_query','_read_axis_position','_disconnect_locked','_finish_scan'}):continue
        signature=inspect.signature(method)
        @functools.wraps(method)
        def wrapper(self,*args,__method=method,__name=name,__signature=signature,**kwargs):
            try:
                requested=dict(__signature.bind(self,*args,**kwargs).arguments);requested.pop('self',None)
            except Exception:requested={'args':args,'kwargs':kwargs}
            call=uuid.uuid4().hex
            emit('operation_intent',operation=__name,call_id=call,requested=requested,simulated=getattr(self,'dry_run',None))
            try:
                result=__method(self,*args,**kwargs)
            except BaseException as exc:
                emit('operation_error',operation=__name,call_id=call,type=type(exc).__name__,error=str(exc))
                raise
            else:
                emit('operation_result',operation=__name,call_id=call,result=result,
                     cached_state={key:getattr(self,key,None) for key in
                                   ('position','raw_position','local_offset','_sensor_home_state','_run_state','error')})
                if __name=='_read_axis_position':
                    RECORDER.position(requested.get('axis'),result,simulated=self.dry_run,generation=self._poll_generation,
                                      reference_transition=self._sensor_home_state.get('running',False))
                return result
            finally:
                try:context_callback(self)
                except Exception as exc:emit('audit_context_error',error=str(exc))
        wrapper._audited=True
        setattr(controller_class,name,wrapper)
