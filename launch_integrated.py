import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
no_device='--no-device' in sys.argv or '--check' in sys.argv or 'mock' in sys.argv
if no_device:
 import serial,cv2
 def blocked(*a,**k):raise RuntimeError('No-device mode: hardware access blocked')
 serial.Serial=blocked;serial.serial_for_url=blocked;cv2.VideoCapture=blocked
import visualizer_server as app
if no_device:
 app.open_esp300=blocked;app.probe_version=blocked;app.prepare_wsl_bridge=blocked
if '--check' in sys.argv:print('Original app import OK; no devices opened; no installation')
else:
 no_browser='--no-browser' in sys.argv
 sys.argv=[sys.argv[0]]+[a for a in sys.argv[1:] if a not in ('--mode','mock','live','--no-device','--no-browser')]
 if not no_browser:sys.argv.append('--open-browser')
 app.main()
