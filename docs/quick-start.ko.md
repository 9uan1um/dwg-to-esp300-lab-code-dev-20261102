# 다른 Windows 컴퓨터에서 실행하기

현재 PC를 껐다 켠 뒤 게시 전 테스트할 때는 [재부팅 테스트 순서](reboot-test.ko.md)를 따라갑니다.

## 배포 ZIP을 받은 경우

1. `FLW-ESP300-Windows-x64.zip`을 쓰기 가능한 폴더에 **모두 압축 해제**합니다. ZIP 안에서 직접 실행하지 않습니다.
2. `FLW-ESP300\dwg-esp300-launch.cmd`를 더블클릭합니다.
3. 브라우저에 `http://127.0.0.1:8768`이 열립니다. 실행 중 CMD 창은 열어 둡니다. Ctrl+C로 종료합니다.

Windows 10/11 x64를 대상으로 합니다. Python·Conda·WSL·usbipd 별도 설치는 필요하지 않습니다. 실행 환경과 라이브러리가 `runtime/`에 포함됩니다. 실행 중에는 인터넷이 필요하지 않습니다. USB 어댑터와 카메라의 Windows 드라이버는 해당 컴퓨터에 준비되어 있어야 합니다. 앱은 드라이버를 설치하거나 교체하지 않습니다.

## GitHub 소스를 받은 경우

같은 `dwg-esp300-launch.cmd`를 실행합니다. `runtime/`이 없으면 처음 한 번 공식 Python 및 PyPA/PyPI 서버에서 실행 환경을 내려받습니다. 첫 실행만 인터넷과 약 1 GB 이상의 여유 공간이 필요합니다. 시스템 Python, PATH, 관리자 권한 또는 Conda는 사용하지 않습니다. 설치 실패 시 이유가 CMD 창에 표시되며 다시 실행할 수 있습니다.

인터넷을 사용할 수 없는 PC에는 소스 ZIP 대신 **실행 환경이 포함된 배포 ZIP**을 전달합니다. 배포 ZIP을 다시 만들 때는 개발 PC에서 `build-portable.cmd`를 실행합니다. 결과는 `dist/FLW-ESP300-Windows-x64.zip`과 SHA-256 파일입니다. 실험 로그·업로드·Git 이력·연구 자료는 배포에 포함하지 않습니다.

## Windows 드라이버가 정상일 때 — 기본 경로

1. ESP300과 RS-232/USB 어댑터를 연결합니다.
2. 앱의 Manual jog에서 **Find Windows ports**를 누릅니다.
3. **Windows COM ports**에서 해당 어댑터를 선택합니다. PL2303 어댑터가 하나면 빈 Port 칸에 자동 입력되지만, 드라이버 정상 판정은 아닙니다. 다른 종류의 USB/RS-232 어댑터나 PC 내장 RS-232 포트도 직접 선택하거나 Port에 `COM3` 같은 이름을 입력할 수 있습니다.
4. 기본 통신 설정은 19200 baud, 8N1, RTS/CTS입니다. **Test hardware link (no motion)**으로 실제 `VE` 버전 응답을 확인합니다. 이 검사는 모터를 켜거나 축을 움직이지 않습니다.
5. 실제 제어를 원할 때 Dry run을 해제하고 Connect합니다. Live Connect는 모터를 켜므로 연결 검사와 구별합니다.

드라이버가 목록에 존재하거나 COM 번호가 보이는 것만으로 작동을 보장하지 않습니다. 포트 열기와 실제 제어기 응답이 성공 기준입니다. 다른 프로그램이 포트를 점유하면 먼저 해당 프로그램에서 연결을 해제합니다.

## Windows 연결이 안 될 때

- WSL 설치가 가능한 경우에만 [WSL 연결 안내](esp300-wsl-connection.ko.md)를 대안으로 사용합니다. `esp300-bridge.cmd`를 별도 창에서 실행한 다음 앱에서 **Use WSL (optional)**을 선택하고 버전을 검사합니다. Use WSL 버튼 자체는 설치나 브리지 실행을 하지 않습니다.
- WSL을 설치할 수 없는 PC라면 호환 Windows 드라이버 또는 호환 RS-232/USB 어댑터를 준비해 COM 경로를 사용합니다. 앱은 WSL 없이 열리며, 드라이버가 준비되기 전에도 도면 편집·미리보기·Dry run을 사용할 수 있습니다.
- WSL에 전달된 USB는 Windows에서 동시에 사용할 수 없습니다. Windows 직접 연결로 돌아가려면 브리지를 종료하고 `usbipd list`로 해당 BUSID를 확인한 뒤 `usbipd detach --busid <BUSID>`를 실행합니다. 앱은 장치를 자동 전달하거나 분리하지 않습니다.
- 연결 실패 시 WSL 설치·드라이버 교체·다른 포트 스캔을 자동으로 수행하지 않습니다. 선택한 포트를 확인한 뒤 연결 방식을 고릅니다.

## 도면·카메라·종료

- 기본 샘플은 함께 제공하는 `drawings/Centered_Square_10mm.dxf`입니다. 개인 PC의 도면 경로에 의존하지 않습니다.
- DXF는 바로 읽습니다. DWG는 설치된 ODA File Converter를 우선 사용하고 없으면 포함된 Aspose.CAD로 변환합니다. Aspose 평가판 제한이 적용될 수 있습니다. 변환 결과를 확인하고 필요하면 CAD에서 DXF로 내보내 사용합니다.
- 카메라 인덱스는 PC마다 다릅니다. 기존 실험실 기본값 2가 작동하지 않으면 0부터 확인합니다. 카메라는 Connect할 때만 열립니다.
- CMD 창의 Ctrl+C는 해당 서버를 종료합니다. `esp300-stop.cmd`는 기본 포트 8768/18768의 앱 및 실행 중인 전용 WSL 브리지를 종료합니다. 다른 포트로 실행한 창은 그 창에서 Ctrl+C로 종료합니다. 장비 동작 중에는 앱에서 작업을 먼저 정지합니다.
- 폴더를 이동할 때는 `runtime/`을 포함한 전체 폴더를 함께 옮깁니다. 새 버전은 새 폴더에 압축을 푸는 것을 권장합니다. 소스의 requirements가 바뀌어 재설치가 필요하면 기존 앱을 종료하고 `runtime`을 `runtime-old`로 이름을 바꾼 뒤 다시 실행합니다.

설치·장비 접근 없이 앱 파일을 검사하려면 CMD에서 `dwg-esp300-launch.cmd -Check`를 실행합니다. 실행 환경이 없으면 이 명령도 먼저 준비합니다. 카메라나 시리얼 포트를 열지 않으며, 드라이버·ESP300 실물 작동을 검증한 것은 아닙니다.

## 폴더 구성

- 루트: 실행 CMD, 서버, 변환기, 공통 연결 모듈, autofocus 모듈, 의존성 목록
- `visualizer/`: 브라우저 화면과 로컬 Three.js
- `tools/`: 실행 환경 준비, 배포 빌드, 선택적인 WSL 연결 도구
- `drawings/`, `example/`: 샘플 도면과 생성 코드 예제
- `docs/`: 사용·연결 안내 및 검증 기록
- `research/`: 원본 연구/CAD 자료. 소스 저장소에서 보관하며 앱 배포에서 제외
- `runtime/`, `uploads/`, `generated/`, `outputs/`, `dist/`: PC별 실행 환경·실행 산출물. Git 제외

참고: [pySerial COM/URL 지원](https://pyserial.readthedocs.io/en/stable/url_handlers.html), [Microsoft USB와 WSL](https://learn.microsoft.com/windows/wsl/connect-usb), [Python 앱 내장 배포](https://docs.python.org/3.12/using/windows.html#the-embeddable-package).
