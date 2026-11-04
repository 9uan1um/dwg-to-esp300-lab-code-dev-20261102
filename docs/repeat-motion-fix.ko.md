# Center / Home 연속 동작 진단과 수정 — 2026-10-27

## 재현한 문제와 발생 계층

실제 ESP300 Version 3.09에서 `/api/jog/sensor-home` 실행 후 서버가 다음 오류를 반환했다.

`Axis X ZS? must enable limit checking and abort on limits. Settings were not changed.`

세 축의 `ZS?` 응답은 모두 `4H`, `ZH?`는 모두 `25H`였다. 센서 탐색 전 Python 서버의 `JogController._sensor_home_worker()`가 `config & 5 == 5`를 요구하여, 이동 명령 `OR`을 보내기 전에 거부했다. Home은 이 사전 검사를 사용하지 않으므로 두 버튼의 성공 조건이 달랐다. 예외 처리가 없는 정지나 DWG 변환 오류로 재현된 것은 아니다.

제조사 ESP300 매뉴얼의 ZS 설명(인쇄 페이지 3-169)에 따르면 비트 0은 소프트웨어 제한 감시, 비트 2는 제한 도달 시 이동 중단이다. 따라서 `4H`는 중단 설정만 있고 감시는 꺼진 상태다.

추가로 Center 성공 시 센서 위치를 로컬 `(0,0,0)`으로 지정하므로, 바로 이어지는 Home은 같은 목적지다. 재연결은 로컬 오프셋을 초기화하므로 재연결 전후에 같은 버튼을 누르더라도 비교 조건이 달라진다. 이것을 다음 명령이 무시된 것으로 해석하면 안 된다.

## 수정

- 세 축 모델, mm 단위, 모터 활성화, 정지 상태, 하드웨어 제한 및 중단 설정, 속도, 기존 `SL/SR` 안의 현재 위치·원점을 모두 검증한다.
- 검증 후 소프트웨어 감시 비트만 누락된 경우 해당 비트를 켜고 설정을 다시 읽는다. 실제 장비에서는 `4H → 5H`. 다른 비트와 `SL/SR`는 유지한다.
- 설정 실패 시 탐색을 시작하지 않는다. 보호 기능을 끄거나 제한 범위를 늘리지 않으며 비휘발성 저장(`SM`)도 하지 않는다. 전원 재가동 시 다음 Center가 다시 검증한다.
- Home은 실제 위치를 읽어서 원점 허용차 0.003 mm 안이면 이동 불필요를 명시한다. 이동 명령 전송을 도착 완료로 표시하지 않는다.
- 새로고침 시 연결 입력란이 기존 서버의 포트·Live/Dry run 모드를 표시한다. 이전에는 기본 Dry run 체크와 실제 연결 상태가 달라질 수 있었다.
- 진단 API에 실제 좌표, ZS, ZH 응답을 추가했다.

## 실제 장비 검증

사용자가 레이저 OFF와 세 축 경로 확보를 확인한 후, 수정 서버를 시작하여 실제 연결에서 수행했다. 중간 재연결은 **0회**다.

1. Center: X/Y/Z 모두 완료, 오류 없음.
2. Home: 이미 로컬 원점이므로 `alreadyHome=true`.
3. X +0.1 mm 이동: 제어기 실제 X 응답 `0.1000 mm` 확인.
4. Home 복귀: 제어기 실제 X 응답 `-0.0005 mm` 확인.
5. 같은 연결에서 Center 재실행: X/Y/Z 모두 완료.
6. Home, X +0.1 mm, Home 복귀를 다시 수행하여 같은 결과 확인.

각 검증 지점에서 세 축 `MD?=1`, `MO?=1`, `ZS?=5H`, `ZH?=25H`, 오류 버퍼 `NO ERROR DETECTED`를 확인했다. 이는 제어기 위치 응답 기준이며 외부 계측기로 위치 정확도를 검증한 것은 아니다.

원시 기록: `../research/verification/repeat-motion-diagnosis/live-sequence.json`.
재현 스크립트: `../research/verification/repeat-motion-diagnosis/verify_live_sequence.py`.
이 스크립트는 실제 이동을 수행하므로 같은 안전 조건과 실행 전제 없이 재실행하지 않는다.

모의 장비·HTTP·RFC2217 회귀 테스트 39개 통과, JavaScript 구문 검사 통과. 브라우저에서 실제 연결 표시 및 Home의 이동 불필요 안내를 확인했다.

검증 후 장비는 로컬 원점 근처에서 정지해 있고 연결은 유지했다. 센서 탐색으로 시료 좌표 정렬이 초기화되었으므로 가공 전에 시료 정렬과 Set local home이 필요하다. 이번 검증은 Center/Home/짧은 Jog 반복이며 전체 가공 작업의 신뢰성을 보증하지 않는다.

제조사 근거: [ESP300 User Manual, ZS](https://www.newport.com/medias/sys_master/images/images/h2f/haa/8797091299358/ESP300-User-Manual.pdf#page=209).
