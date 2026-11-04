# ESP300 연결 및 재연결 설명서

이 설명서는 **Windows 드라이버를 사용할 수 없을 때 선택하는 WSL 대안**을 다룹니다. Windows COM 연결이 정상이라면 브리지는 필요 없습니다. 새 PC의 실행과 Windows 직접 연결은 [빠른 시작](quick-start.ko.md)을 먼저 확인하세요. 아래의 실물 검증 기록은 당시 실험실 PC에 대한 기록입니다.

Windows의 기존 Prolific 드라이버를 유지하면서, 같은 RS232–USB 케이블을 WSL의 Linux 드라이버로 사용합니다.

**이 PC의 설치는 끝났습니다.** 평소 사용하거나 PC를 재부팅한 뒤에는 아래의 **매번 사용하는 7단계**부터 진행하면 됩니다. 설치 스크립트를 매번 실행할 필요는 없습니다.

2026년 10월 27일에는 웹앱과 명령줄 양쪽에서 실제 제어기의 `ESP300 Version 3.09` 응답을 확인했습니다. 세 축의 모델과 위치도 읽었습니다. 이 확인 과정에서는 모터를 움직이지 않았으므로, 실제 가공 경로와 이동 방향은 별도로 확인해야 합니다.

[English version](esp300-wsl-connection.md)

## 매번 사용하는 7단계: PC 재부팅 후, USB가 뽑힌 상태에서 시작

이 순서는 **WSL·usbipd·프로그램 설치가 끝난 현재 실험실 PC**를 기준으로 합니다. 처음 설치하는 다른 PC는 문서 아래의 설치 절차를 먼저 진행합니다.

이 설명서의 명령은 **명령 프롬프트(CMD)** 창에 입력합니다. 평소 실행은 `esp300-bridge.cmd`와 `dwg-esp300-launch.cmd` 두 배치 파일로 합니다. 배치 파일이 검증된 PowerShell 스크립트를 내부에서 호출하므로 PowerShell 창을 직접 열 필요는 없습니다. 실행 정책 우회는 배치 파일의 자식 프로세스에만 적용되며 PC 전체 정책은 변경하지 않습니다.

### 1. 컴퓨터를 켜고 Windows에 로그인한다

PC가 꺼졌다 켜지면 이전 WSL·브리지·웹앱이 계속 실행 중이라고 가정하지 않습니다. Windows의 COM 번호도 외워서 입력하지 않습니다.

### 2. ESP300 전원을 켜고, 빠져 있는 USB를 다시 꽂는다

ESP300 LCD에 세 축의 좌표가 나오는지 확인합니다. RS232 쪽은 ESP300에, USB 쪽은 PC에 연결되어 있어야 합니다. **USB가 뽑힌 상태로는 브리지와 실제 제어기 연결을 완료할 수 없습니다.**

PC 쪽 USB를 다시 연결하는 단계입니다. 스테이지와 제어기 사이의 모터 케이블은 이 절차에서 바꾸지 않습니다.

### 3. 일반 CMD 창에서 WSL을 준비한다

시작 메뉴에서 `cmd`를 검색해 **명령 프롬프트**를 열고 다음 두 줄을 실행합니다.

```bat
cd /d "C:\path\to\FLW-ESP300"
wsl.exe -d FLW-ESP300 -u flw -- echo WSL-ready
```

**정상 표시:** `WSL-ready`가 나오고 `C:\...>` 프롬프트로 돌아옵니다. Ubuntu 터미널을 따로 열어둘 필요는 없습니다. 다음 브리지 스크립트도 필요하면 WSL을 다시 시작합니다.

배포판이 없다는 오류가 나오면 설치가 완료되지 않은 PC입니다. 브리지 명령을 반복하지 말고 아래 설치 절차부터 확인합니다.

### 4. 같은 창에서 USB를 WSL에 전달하고 브리지를 연결한다

```bat
esp300-bridge.cmd
```

스크립트가 `067b:2303` 어댑터의 현재 BUSID를 **자동 검색**합니다. USB 단자를 바꿔도 예전 `2-4`나 COM9를 외워서 입력할 필요가 없습니다. 처음 쓰는 단자라 공유 등록이 필요하면 Windows 관리자 승인 창이 나타납니다. 승인 후 스크립트가 계속 진행합니다.

**USB가 없으면:** `No 067b:2303 USB adapter is plugged in`이라고 안내하고 중단합니다. PC 쪽 USB를 꽂고 위 명령을 다시 실행합니다.

정상 진행 중에는 `Selected adapter`, `[1/4]`부터 `[4/4]`까지 표시된 뒤 다음 문구가 나옵니다.

```text
ESP300 BRIDGE RUNNING IN THIS WINDOW. Keep it open. Press Ctrl+C to stop.
... Listening on 127.0.0.1:22170 -> /dev/ttyUSB0 (one client at a time)
```

**이 CMD 창이 브리지를 직접 실행합니다. 사용 중 창을 열어 두고 5번은 두 번째 CMD 창에서 진행합니다.** 정상 실행 중에는 입력 프롬프트로 돌아오지 않습니다. `/dev/ttyUSB0`의 숫자는 달라질 수 있습니다.

브리지만 종료하려면 이 창에서 **Ctrl+C**를 누릅니다. `Terminate batch job (Y/N)?`가 나오면 **Y**를 입력합니다.

기존 브리지가 이미 실행 중이면 새 실행기는 이를 조용히 재사용하지 않고 오류를 표시합니다. 기존 실행 창에서 Ctrl+C로 종료하거나, 별도 CMD에서 아래 명령으로 ESP300 서버들을 먼저 종료한 뒤 다시 시작합니다.

```bat
esp300-stop.cmd
```

USB를 뺐다 꽂은 후에는 기존 브리지와 앱의 사용을 끝내고 이 명령부터 다시 실행합니다. `Shared`나 `Attached` 표시만 보고 브리지 단계를 생략하지 않습니다. `RUNNING`/`Listening`은 브리지 준비 완료이며, ESP300 응답 성공 여부는 7번에서 확인합니다.

동일한 VID:PID의 어댑터가 둘 이상일 때만 `usbipd list`로 확인한 실제 BUSID를 명시합니다.

```bat
"C:\Program Files\usbipd-win\usbipd.exe" list
REM Example only: use the current BUSID shown for 067b:2303.
esp300-bridge.cmd -BusId 2-4
```

### 5. 새 일반 CMD 창에서 웹앱을 실행한다

4번 A의 브리지 창은 그대로 두고 **두 번째 CMD 창**을 엽니다. 다음 두 줄을 실행합니다.

```bat
cd /d "C:\path\to\FLW-ESP300"
dwg-esp300-launch.cmd
```

다음 문구가 나오면 웹서버가 준비된 것입니다.

```text
ESP300 WEB SERVER RUNNING: http://127.0.0.1:8768
Keep this window open. Press Ctrl+C to stop the web server.
```

**웹서버도 이 CMD 창에서 직접 실행됩니다.** 브라우저는 자동으로 열리며 주소는 **<http://127.0.0.1:8768>**입니다. 사용 중 이 두 번째 CMD 창도 열어 둡니다. 정상 실행 중에는 입력 프롬프트로 돌아오지 않습니다. 프로그램 업데이트 직후 기존 브라우저 탭을 재사용한다면 새로고침합니다.

웹서버만 종료하려면 이 창에서 **Ctrl+C**를 누릅니다. `Terminate batch job (Y/N)?`가 나오면 **Y**를 입력합니다. 브라우저 탭만 닫는 것은 서버 종료가 아닙니다. 이미 8768 서버가 실행 중이면 중복 실행 오류가 나며, 먼저 기존 창에서 종료하거나 `esp300-stop.cmd`를 실행합니다.

실행기가 Python 환경 오류를 표시하면 브라우저에서 Connect를 반복하지 말고 해당 오류를 먼저 확인합니다. 배치 파일은 오류가 나면 메시지를 읽을 수 있게 일시 정지합니다. 현재 실행기는 앱 폴더에 포함된 `runtime\python.exe`를 사용하며, Conda 환경 활성화는 필요 없습니다.

### 6. 웹앱에서 ESP300에 실제 연결한다

오른쪽 **Jog → Manual jog (ESP300)**에서 다음 순서로 조작합니다. 카메라 영역의 Connect는 별도 기능입니다.

1. **Use WSL**을 누릅니다.
2. 주소가 `rfc2217://127.0.0.1:22170`, Baud가 `19200`인지 확인합니다.
3. **Dry run (no hardware) 체크를 해제**합니다.
4. **Connect**를 누릅니다.

**정상 표시:**

```text
Connected: rfc2217://127.0.0.1:22170 @ 19200
Controller axes: X=1, Y=2, Z=3
```

실제 Connect는 세 축의 **모터를 활성화**하고 현재 위치를 읽습니다. 홈 이동이나 가공 경로를 자동 실행하지는 않습니다. 연결 절차에서 Jog·Home·Go·Run on machine을 누를 필요는 없습니다.

`Connected (dry run, ...)`은 시뮬레이션 상태입니다. 실제 연결 성공 표시로 간주하지 않습니다.

### 7. 연결을 유지한 채 실제 통신 성공을 테스트한다

6번의 `Connected` 상태에서 **Test hardware link (no motion)**를 누릅니다.

**정상 표시:**

```text
Version reply: ESP300 Version 3.09. Test complete; live connection kept open.
```

위쪽 상태도 `Connected: ... @ 19200`으로 남아 있어야 합니다. 이 버튼은 **이미 열린 연결을 재사용**해 `VE` 버전 조회만 합니다. 연결을 다시 열거나 닫지 않으며 모터·홈·이동 명령을 추가로 보내지 않습니다. 작업 실행 중에는 테스트를 막으므로, 7번 검증을 끝낸 뒤 작업을 시작합니다.

**최종 성공 기준은 `Connected`와 실제 버전 응답 두 가지를 함께 확인하는 것입니다.** `WSL-ready`, `Listening`, `Ready`만으로 ESP300 응답까지 성공했다고 판단하지 않습니다.

연결 전에 이 테스트를 눌러도 버전 조회는 가능합니다. 그때는 임시 연결을 사용하므로 테스트 후 `Disconnected`가 유지되고 `temporary test connection released`가 표시됩니다. 이 경우와 6→7 순서의 `live connection kept open`을 구분합니다.

### 이 절차의 검증 범위

CMD 배치 실행과 Windows PowerShell 5.1/7 내부 스크립트 실행, BUSID 자동 검색, 실제 `ESP300 Version 3.09` 응답을 확인했습니다. CMD 창에서 직접 실행, Ctrl+C 종료, 전체 종료 명령으로 실제 서버들이 종료되는 것도 확인했습니다. 서버·통신 테스트 14개와 USB 자동 검색 조건 5개를 검증했습니다. Connect 후 동작은 가짜 장치로 검증했고, 실제 열린 시리얼 연결에서도 VE를 두 번 조회하여 같은 연결이 유지됨을 확인했습니다. 이 검증 과정에서 실제 모터 활성화·이동 명령은 보내지 않았습니다. 실제 PC 전원 종료·물리적인 USB 분리부터 7번까지를 연속 수행한 검증과 실제 모터 구동 검증은 별도입니다.

## 축 배정과 버튼의 의미

아래 배정은 제어기에서 읽은 모델과 사용자가 확인한 축 이름을 기준으로 합니다.

| 웹앱 축 이름 | 제어기 채널 | 스테이지 모델 |
|---|---|---|
| X | Axis 1 | M-ILS150PP |
| Y | Axis 2 | UTS100PP |
| Z | Axis 3 | GTS150 |

프로그램의 배정은 **X=1, Y=2, Z=3**입니다. 스테이지가 세워져 있다는 이유로 해당 축을 Z로 바꾸지 않습니다. 수동 Jog, 웹앱의 경로 실행, 새로 내보낸 코드는 `esp300_connection.py`의 같은 축 배정을 사용합니다.

이 장치에서는 제어기 2번 축의 양수 방향이 아래쪽이므로, **Y+가 위쪽**이 되도록 `ESP300_AXIS_SIGNS`의 Y를 `-1`로 보정합니다. 수동 이동·좌표 이동·도면 실행·위치 읽기에 같은 보정이 적용됩니다. 수정 후에는 Python 웹 서버를 재시작하고 다시 연결한 뒤 시료 기준점에서 **Set local home**을 다시 설정합니다. 브라우저 새로고침만으로는 반영되지 않습니다. 로컬 홈 설정 전 화면 Y는 제어기 Y와 부호가 반대입니다. 이전에 내보낸 Python 코드·노트북은 다시 내보내야 보정이 적용됩니다.

| 버튼 또는 설정 | 실제 동작 |
|---|---|
| Use WSL | 연결 주소 입력란을 WSL 주소로 바꿈. 장치에 연결하지는 않음 |
| Test hardware link (no motion) | 실제 연결 상태에서는 그 연결로 버전만 읽고 유지. 연결 전에는 임시 연결로 조회 후 닫음 |
| Dry run을 체크한 Connect | 하드웨어 없이 시뮬레이션에 연결 |
| Dry run을 해제한 Connect | 통신을 열고 세 축 모터를 활성화한 뒤 위치를 읽음 |
| Disconnect | 통신을 닫으면서 각 축에 모터 비활성화 명령을 보냄 |
| Home (0, 0, 0) | 현재 로컬 좌표의 0,0,0으로 이동. 기계 원점 탐색 명령은 아님 |
| Center (sensors) | X → Y → Z 순서로 중앙 원점 센서를 탐색. 완료 후 시료 정렬 및 Set local home 재설정 필요. [한국어 사용 절차](central-sensor-home.ko.md) |
| Set local home (here = 0) | 현재 위치에 도면 중심 좌표를 부여하고 참조점으로 저장. 이동하지 않음 |
| Go to local home | 저장된 참조점으로 실제 이동 |

`Set local home`은 버튼 문구에 `here = 0`이 있지만, 현재 구현은 확인창에 나오는 **도면 중심 X/Y와 초점 Z 좌표**를 현재 위치에 부여합니다. 기본값은 X=12.5, Y=12.5, Z=0입니다. 따라서 `Home (0, 0, 0)`과 `Go to local home`의 이동 목적지는 다를 수 있습니다. 확인창의 좌표를 보고 구분합니다.

**Disconnect는 단순히 웹 연결만 끊는 버튼이 아닙니다.** 모터 유지력에 의존하는 하중이 있다면 모터 비활성화의 영향을 고려해야 합니다.

브리지는 한 번에 한 프로그램이 사용합니다. 웹앱에 실제 연결한 동안에는 외부 시리얼 프로그램이나 명령줄 버전 조회를 동시에 실행하지 않습니다. 웹앱 안의 Test hardware link 버튼은 작업이 멈춰 있을 때 기존 연결을 재사용하므로 연결 후에도 사용할 수 있습니다.

## 사용을 마치거나 USB를 분리할 때

작업이 실행 중이면 먼저 작업을 정지하고 실제 이동이 끝났는지 확인합니다. **서버 종료는 기계의 비상정지를 대신하지 않습니다.** 웹앱의 Disconnect는 모터 비활성화 명령을 보내므로 모터 유지력이 필요한 경우 구분해서 사용합니다.

- 브리지만 종료: 첫 번째 CMD 창에서 **Ctrl+C**.
- 웹서버만 종료: 두 번째 CMD 창에서 **Ctrl+C**.
- `Terminate batch job (Y/N)?`가 표시되면 **Y**.
- 두 서버를 한 번에 종료: 프로젝트 폴더의 별도 CMD에서 다음 명령 실행.

```bat
esp300-stop.cmd
```

전체 종료 도구는 ESP300 웹서버(8768), ESP300 미리보기 서버가 있으면 해당 서버(18768), 이 프로젝트의 WSL 브리지(22170)를 종료합니다. 모터 켜기·끄기 명령은 보내지 않습니다. 실행 중인 작업은 먼저 끝내거나 정지해야 합니다.

USB를 Windows 쪽으로 돌려놓으려면 서버를 종료한 다음 일반 CMD에서 실행합니다.

```bat
set /p "ESP300_BUSID=Current BUSID of the 067b:2303 device: "
"C:\Program Files\usbipd-win\usbipd.exe" detach --busid %ESP300_BUSID%
```

`detach` 후에는 Windows가 어댑터를 다시 사용합니다. 다만 기존 Windows 드라이버의 포트 열기 문제까지 해결되는 것은 아닙니다. ESP300은 다음에도 WSL 경로로 연결하면 됩니다.

공유 등록 자체를 없애려면 관리자 권한 CMD에서 `unbind`를 실행합니다. 평소 사용을 마칠 때마다 할 필요는 없습니다.

```bat
set /p "ESP300_BUSID=Current BUSID of the 067b:2303 device: "
"C:\Program Files\usbipd-win\usbipd.exe" unbind --busid %ESP300_BUSID%
```

PC를 재부팅하거나 USB를 뺐다 꽂으면 연결이 끊길 수 있습니다. 다음 사용 시에는 현재 BUSID를 확인하고 브리지부터 다시 실행합니다.

## 연결이 안 될 때 확인할 것

| 증상 또는 메시지 | 확인할 것과 해결 순서 |
|---|---|
| 목록에 `067b:2303`이 없음 | USB가 PC에 연결됐는지 확인하고 `usbipd list`를 다시 실행. 이 단계에서는 브리지를 시작할 수 없음 |
| `not the expected 067b:2303 serial adapter` | 다른 장치의 BUSID를 입력했을 수 있음. 목록에서 VID:PID가 일치하는 행을 다시 확인 |
| `No 067b:2303 USB adapter is plugged in` | PC 쪽 USB를 다시 꽂고 4번 명령을 재실행 |
| USB 공유 등록 관리자 승인 창이 취소됨 | 4번을 다시 실행하고 해당 어댑터의 공유 등록을 승인 |
| `NameError: name 'Expected' is not defined`, `found:: command not found`, 또는 `null-valued expression` | 이전 스크립트의 PowerShell 5.1 따옴표 처리 오류. 수정된 `tools/start_esp300_bridge.ps1`과 새 `tools/esp300_bridge_runtime.py`를 함께 사용하여 재실행 |
| `Ready. Reusing...` 후 프롬프트로 돌아옴 | 이전 버전 실행기임. 현재 버전은 창에서 직접 실행하고 중복 실행을 거부함. 기존 서버 종료 후 수정된 CMD 사용 |
| `A bridge/listener is already running` 또는 `A server already uses port` | 기존 실행 창에서 Ctrl+C 또는 `esp300-stop.cmd`로 종료한 뒤 다시 시작 |
| `Could not uniquely locate the Linux serial device` | USB 전달 또는 Linux 장치 인식 상태를 확인. 아래의 Linux 포트 조회 실행. 같은 VID:PID의 장치가 여러 개 있으면 하나로 특정해야 함 |
| `Permission denied` | Linux 사용자 `flw`의 `dialout` 그룹과 udev 규칙 확인. 아래의 Linux 설정 스크립트를 다시 실행하여 복구 가능 |
| `Address already in use` | 같은 포트의 브리지가 이미 실행 중일 수 있음. 기존 브리지를 사용하거나, 기존 브리지를 종료한 뒤 한 개만 실행 |
| `WinError 10061` 또는 연결 거부 | 웹앱이 WSL 브리지에 연결하지 못함. 브리지 창의 `Listening` 문구, 주소 `rfc2217://127.0.0.1:22170`, 포트 번호를 확인 |
| `No complete VE reply` | 브리지 준비와 별개로 제어기 응답이 없음. ESP300 전원을 켜 LCD에 좌표가 표시되는지 먼저 확인하고, RS232 연결과 통신 속도를 확인 |
| 연결 전에 테스트하여 `Disconnected` | 임시 연결 테스트의 정상 결과. 6번 Connect 후 7번 테스트를 순서대로 진행 |
| `Connected` 후 테스트에서 연결이 닫힘 | 수정된 서버인지 확인. 새 코드 반영에는 서버 재시작이 필요함 |
| `Stop the current job before testing` | 실행 중 작업이 끝나고 실제 이동이 멈춘 뒤 테스트 |
| `Connected (dry run, ...)`만 표시됨 | 시뮬레이션 상태. 실제 제어기 연결은 Dry run 해제 후 Connect |
| `Axis ... position read failed` | 연결 후 해당 축의 위치 응답을 받지 못함. 화면의 오류를 기록하고 아래 로그를 확인. 가공 실행으로 통신을 시험하지 않음 |
| `PL2303HXA PHASED OUT...`가 Windows 목록에 계속 보임 | Windows 드라이버가 표시하는 기존 장치 설명. WSL 경로의 성공 여부는 Linux 장치 생성과 실제 `VE` 응답으로 확인 |

Linux에서 USB 어댑터가 보이는지 확인하는 명령입니다. 장치를 움직이지 않습니다.

```bat
wsl.exe -d FLW-ESP300 -u flw -- python3 -m serial.tools.list_ports -v
```

목록에서 `USB VID:PID=067B:2303`인 장치를 찾습니다. 설정 당시에는 `/dev/ttyUSB0`으로 표시됐습니다. 장치 번호는 바뀔 수 있으며, 시작 스크립트가 자동으로 찾습니다.

웹앱 대신 명령줄에서 버전만 확인하려면, 웹앱이 실제 연결 중이지 않은 상태에서 프로젝트 폴더에서 실행합니다.

```bat
runtime\python.exe esp300_connection.py
```

성공 시 출력의 `versionReply`가 `ESP300 Version 3.09`입니다. 이 명령도 버전만 읽고 종료합니다.

셋업 과정에서 백그라운드로 시작한 브리지와 웹앱의 로그는 `research\verification\esp300-virtualization`에 있습니다. 이후 설명서대로 직접 실행한 브리지는 실행한 CMD 창에서 오류를 확인합니다.

## 연결 방식과 포트 번호 이해하기

현재 통신은 다음 경로로 전달됩니다.

```text
Windows의 DWG to ESP300 웹앱
    ↓ rfc2217://127.0.0.1:22170
WSL의 통신 브리지
    ↓ /dev/ttyUSB0 등
Linux의 pl2303 드라이버
    ↓ USB–RS232 어댑터와 RS232 케이블
ESP300 제어기
```

| 이름 | 의미 | 이 구성에서 쓰는 곳 |
|---|---|---|
| COM5, COM8, COM9 | Windows가 시리얼 장치에 붙이는 이름 | 기존 Windows 연결 경로. WSL 주소 입력란에 쓰지 않음 |
| BUSID | USB/IP가 PC의 USB 장치를 구분하는 식별자 | `bind`, `attach`, 시작 스크립트, `detach` |
| `/dev/ttyUSB0` | Linux가 만든 시리얼 장치 이름 | Linux 브리지가 어댑터에 접근할 때 사용 |
| `127.0.0.1:22170` | 이 PC 안에서 브리지에 접속하는 주소와 포트 | 웹앱의 `Port / WSL address` 입력란 |
| `127.0.0.1:8768` | 웹앱 화면에 접속하는 주소와 포트 | 웹브라우저 주소창 |
| ASCII | 명령 문자를 바이트로 표현하는 방식 | ESP300 명령과 응답의 문자 인코딩 |

COM 번호와 인코딩은 서로 다른 설정입니다. COM 번호를 바꾼다고 Windows 드라이버가 지원하지 않는 칩을 지원하게 되지는 않습니다.

이번에는 USB 장치 자체를 WSL로 전달하고, Linux의 `pl2303` 드라이버로 사용했습니다. **기존 Windows Prolific 드라이버를 구형으로 교체하지 않았습니다.** WSL에 전달된 동안에는 Windows 시리얼 프로그램이 같은 USB 장치를 동시에 사용할 수 없습니다.

| 통신 설정 | 확인한 값 |
|---|---|
| Baud rate | 19200 |
| 데이터 비트 / 패리티 / 정지 비트 | 8 / 없음 / 1, 즉 8N1 |
| 흐름 제어 | RTS/CTS |
| 웹앱의 시리얼 연결 주소 | `rfc2217://127.0.0.1:22170` |

카메라와 CAD 변환 프로그램은 계속 Windows 환경에서 실행합니다. Linux는 이 USB 어댑터의 통신을 담당합니다. 브리지는 로컬 주소에만 열며, 다른 PC에서 접속하도록 설정하지 않습니다.

## 처음 설치하거나 Linux 설정을 복구할 때

**현재 PC에서는 설치가 완료됐으므로, 평소 연결할 때는 이 절차를 건너뜁니다.** 다른 PC에서 WSL 대안을 준비할 때는 예시의 앱 폴더 경로를 실제 위치로 바꿉니다. Windows 앱은 폴더에 포함된 Python을 사용하므로 Conda 경로를 설정할 필요가 없습니다.

처음 Windows 구성요소를 설치할 때는 관리자 권한 CMD에서 실행합니다.

```bat
cd /d "C:\path\to\FLW-ESP300"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\setup_esp300_virtualization.ps1
```

이 스크립트는 Virtual Machine Platform을 켜고 WSL과 usbipd-win을 설치합니다. 기존 Prolific 드라이버를 다운그레이드하지 않으며 자동 재부팅하지 않습니다. 재부팅이 필요하면 작업을 저장한 뒤 Windows를 다시 시작합니다.

Windows 재부팅 후 일반 CMD에서 실행합니다. 이 단계까지는 USB를 빼둬도 됩니다.

```bat
cd /d "C:\path\to\FLW-ESP300"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\setup_esp300_linux.ps1
```

전용 Ubuntu 배포판 `FLW-ESP300`, 사용자 `flw`, `dialout` 그룹 권한, pySerial 및 udev 규칙을 준비합니다. Linux 권한이나 규칙을 복구할 때도 이 Linux 설정 스크립트를 사용할 수 있습니다.

usbipd-win 설치로 USB 전달용 서비스·드라이버·방화벽 규칙이 추가됩니다. 따라서 기존 Prolific 드라이버는 유지하지만, Windows에 아무 변경도 없는 방식은 아닙니다.

## 검증 기록과 파일 위치

다음은 **2026년 10월 27일 셋업 당시 확인한 값**입니다. 버전 번호가 달라졌다고 곧바로 고장으로 판단하지 않습니다.

| 항목 | 확인 결과 |
|---|---|
| 제어기 응답 | `ESP300 Version 3.09` |
| Windows Prolific 드라이버 | 3.9.6.0, `oem188.inf` |
| WSL / usbipd-win | 2.7.14.0 / 5.3.0 |
| Linux 배포판 | Ubuntu 24.04, 배포판 이름 `FLW-ESP300` |
| Linux 커널 | `6.18.33.2-microsoft-standard-WSL2` |
| Linux Python / pySerial | 3.12.3 / 3.5 |
| 실제 장비 확인 | 버전 응답, 세 축의 모델 ID와 위치 조회 성공 |
| 소프트웨어 확인 | 가짜 장치를 사용한 테스트 9개 통과, Windows↔WSL 루프백 통신 성공 |
| 실제 이동·가공 | 이번 연결 검증에서 실행하지 않음 |

실제 경로 실행에 앞서 소규모 이동으로 축 방향과 동작을 확인해야 합니다. USB/IP의 통신 지연이 있으므로 기존 가공 타이밍이 그대로 맞는지는 실제 동작으로 확인합니다.

| 파일 | 용도 |
|---|---|
| [`dwg-esp300-launch.cmd`](../dwg-esp300-launch.cmd) | 두 번째 CMD에서 웹서버 직접 실행, Ctrl+C로 종료 |
| [`esp300-bridge.cmd`](../esp300-bridge.cmd) | 첫 번째 CMD에서 브리지 직접 실행, Ctrl+C로 종료 |
| [`esp300-stop.cmd`](../esp300-stop.cmd) | ESP300 웹서버·브리지 전체 종료 |
| [`launch_dwg_to_esp300.ps1`](../launch_dwg_to_esp300.ps1) | 배치 파일이 내부에서 호출하는 웹앱 실행 코드 |
| [`tools/start_esp300_bridge.ps1`](../tools/start_esp300_bridge.ps1) | USB 전달과 Linux 브리지 실행 |
| [`esp300_connection.py`](../esp300_connection.py) | 공통 통신 설정, 축 배정, 버전 조회 |
| [`tools/esp300_serial_bridge.py`](../tools/esp300_serial_bridge.py) | Linux에서 실행하는 통신 브리지 |
| [`tools/setup_esp300_virtualization.ps1`](../tools/setup_esp300_virtualization.ps1) | Windows 최초 설치 |
| [`tools/setup_esp300_linux.ps1`](../tools/setup_esp300_linux.ps1) | Linux 설치 및 통신 권한 설정 |

새로 내보낸 제어 스크립트는 WSL 연결 주소를 지원합니다. 이전에 내보낸 파일은 자동 수정되지 않으므로, 해당 파일의 연결 코드가 WSL 주소를 지원하는지 확인하거나 웹앱에서 다시 내보냅니다.

관련 원문 자료는 [영문 설명서의 참고 링크](esp300-wsl-connection.md)에 있습니다.
