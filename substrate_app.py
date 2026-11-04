"""Local interactive simulator. Standard library only; never imports legacy hardware code."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import secrets
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import webbrowser

ROOT=Path(__file__).resolve().parent
# Embedded runtimes include their owning checkout. Always use THIS application.
sys.path.insert(0,str(ROOT))
import app_audit
from substrate_engine import Experiment, live_connect, enable_motors

class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self, address, experiment):
        super().__init__(address,Handler)
        self.experiment=experiment;self.token=secrets.token_urlsafe(32)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*args):self.server.experiment.audit.emit('mock_http_access',message=fmt%args)
    def _host_ok(self):
        expected={'127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)}
        return self.headers.get('Host') in expected
    def send(self,code,payload,kind='application/json'):
        data=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode() if kind=='application/json' else payload
        self.send_response(code);self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(data)
    def do_GET(self):
        if not self._host_ok():self.send(403,{'error':'Unexpected host'});return
        if self.path=='/api/status':self.send(200,self.server.experiment.snapshot());return
        assets={'/':('index.html','text/html'),'/app.js':('app.js','text/javascript'),'/style.css':('style.css','text/css')}
        if self.path not in assets:self.send(404,{'error':'Not found'});return
        name,kind=assets[self.path];data=(ROOT/'substrate_ui'/name).read_bytes()
        if name=='index.html':data=data.replace(b'__SESSION_TOKEN__',self.server.token.encode())
        self.send(200,data,kind)
    def do_POST(self):
        experiment=self.server.experiment
        if not self._host_ok() or self.headers.get('X-Session-Token')!=self.server.token:
            self.send(403,{'error':'Session token required'});return
        try:
            if self.headers.get('Content-Type')!='application/json':raise ValueError('JSON required')
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=131072:raise ValueError('Invalid request size')
            body=json.loads(self.rfile.read(size),parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            if not isinstance(body,dict):raise ValueError('JSON object required')
            experiment.audit.emit('mock_api_intent',path=self.path,body=body)
            routes={'/api/config':lambda:experiment.configure(**body),
                    '/api/home':lambda:experiment.set_home(body['xyz']),
                    '/api/manual':lambda:experiment.manual(**body),
                    '/api/preview':experiment.preview_recipe,
                    '/api/validate':lambda:experiment.validate(body.get('preview_id')),
                    '/api/start':lambda:experiment.start(body.get('preview_id')),
                    '/api/cancel':experiment.cancel,
                    '/api/live/connect':live_connect,'/api/live/enable':enable_motors}
            if self.path=='/api/shutdown':
                experiment.close();self.send(200,{'closing':True});threading.Thread(target=self.server.shutdown,daemon=True).start();return
            if self.path not in routes:self.send(404,{'error':'Unknown action'});return
            result=routes[self.path]()
            experiment.audit.emit('mock_api_result',path=self.path,result=result)
            self.send(200,result)
        except Exception as exc:
            experiment.audit.emit('mock_api_error',path=self.path,error=str(exc))
            self.send(400,{'error':str(exc)})

def main(argv=None):
    p=argparse.ArgumentParser(description='Substrate MOCK workflow only. No hardware connections.')
    p.add_argument('--mode',choices=['mock','live'],default='mock')
    p.add_argument('--port',type=int,default=0,help='0 selects a free loopback port')
    p.add_argument('--no-browser',action='store_true');p.add_argument('--check',action='store_true')
    args=p.parse_args(argv)
    if args.mode!='mock':p.error('Live mode is fail-closed. Physical mapping, clearance and reliable beam preflight are unverified.')
    if not 0<=args.port<=65535:p.error('Port must be 0..65535')
    if sys.version_info<(3,10):p.error('Python 3.10 or later is required')
    if args.check:
        print(json.dumps({'status':'ok','mode':'mock','python':sys.version.split()[0],
                          'root':str(ROOT),'dependencies':'Python standard library only',
                          'hardware_imported':False,'downloads':False}));return 0
    recorder=app_audit.start(ROOT/'logs'/'substrate_sessions')
    experiment=None;server=None
    try:
        experiment=Experiment(recorder);server=Server(('127.0.0.1',args.port),experiment)
        url='http://127.0.0.1:'+str(server.server_port)
        recorder.emit('mock_server_ready',url=url);recorder.checkpoint()
        print('SUBSTRATE MOCK READY '+url,flush=True)
        print('No device connection. Close with the UI Exit button or Ctrl+C.',flush=True)
        if not args.no_browser:webbrowser.open(url)
        server.serve_forever(poll_interval=.1)
    except KeyboardInterrupt:pass
    finally:
        if experiment:experiment.close()
        if server:server.server_close()
        recorder.close()
    return 0

if __name__=='__main__':raise SystemExit(main())
