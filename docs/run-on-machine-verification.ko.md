# Run on machine 실제 도면 실행 검증 — 2026-10-27

## 시험 조건

- 사용자 확인: 레이저 OFF, 현재 센서 원점 기준 X/Y 각각 약 ±8.804 mm 및 Z 0~-1 mm의 이동 경로 확보.
- 도면: `uploads/bd5ad16e_Line_20mm_20000um.dwg`.
- 웹앱의 Open path로 원본 DWG를 열고 Run on machine 버튼을 눌러 실행.
- Fit longest 20 mm, 회전 45도, 기존 원형 영역 제한 적용. 결과 대각선의 실제 경로 길이는 24.899999 mm다. 파일명 자체가 실제 실행 길이를 뜻하지 않는다.
- 현재 위치를 시험용 도면 중심 `(12.5,12.5,0)`으로 지정했다. 시료 가공 정렬 정확도를 검증한 것은 아니다.
- Live 연결: `rfc2217://127.0.0.1:22170`, 19200 baud, `dryRun=false`; 자동 초점 OFF.
- 경로 속도 0.4 mm/s, 구간 사이 이동 1.0 mm/s, Z 속도 0.3 mm/s.

## 첫 전체 실행 결과

**5/5 구간 모두 완료. 첫 동작 이후 중단되는 증상은 재현되지 않았다.**

| 완료한 구간 | 동작 | 첫 관찰부터 경과 시간 |
|---|---|---:|
| 1 | Z -1 mm 후퇴 | 3.407초 |
| 2 | 대각선 시작점으로 X/Y 이동 | 16.110초 |
| 3 | Z 0 mm 복귀 | 19.657초 |
| 4 | 24.9 mm 대각선 전체 이동 | 81.938초 |
| 5 | 마지막 Z -1 mm 후퇴 | 85.297초 |
| 최종 완료 | `running=false, index=5, total=5, done=true, error=null` | 85.563초 |

관찰 간격은 약 0.2초와 HTTP 응답 시간을 합한 값이다. 시작 명령 시점 자체가 아니라 첫 실행 관찰부터 측정했다. 총 297개 상태·좌표 표본을 저장했다. 상태 API의 위치는 서버가 보유한 값이며 구간 전환 시 명령 목표가 잠깐 포함될 수 있으므로, 최종 위치는 별도 제어기 TP 응답으로도 확인했다.

최종 원시 제어기 좌표는 X=8.8030 mm, Y=-8.8035 mm, Z=-1.00000 mm. 세 축 모두 `MD?=1`(이동 완료), `MO?=1`, 축 오류 0, 전체 오류 버퍼 `NO ERROR DETECTED`였다. 웹 화면에서도 `Run complete.`와 84.7/84.7초 표시를 확인했다. 84.7초는 계획 시간이며 실제 관찰 시간과 구분해야 한다.

첫 실행 후 같은 연결에서 `Go to local home`으로 시험 도면 중심에 복귀했고, 실제 좌표가 원점 허용 범위 안이며 세 축 모두 정지했음을 확인했다.

## 기록과 검증 범위

- `../research/verification/run-machine-verification/plan.json`: 원본 DWG를 웹앱 API로 계획한 전체 5구간.
- `../research/verification/run-machine-verification/run-1.json`: 실제 실행 진행·좌표·최종 진단.
- `../research/verification/run-machine-verification/center-between-runs.json`: 중심 복귀 확인.
- `../research/verification/run-machine-verification/observe_run.py`: 읽기 전용 관찰 스크립트. 이동을 시작하지 않는다.

두 번째 반복 실행은 브라우저 확인창 처리 지연 후 시작되었고, 같은 연결에서 최종 `done=true, index=5, total=5, error=null` 및 경로 끝점 도착을 확인했다. 실제 원시 좌표는 첫 실행과 같은 X=8.8030, Y=-8.8035, Z=-1.00000 mm였으며, 세 축 모두 `MD?=1`, `MO?=1`, 오류 0이었다. 웹 화면의 `Run complete.`도 확인했다.

다만 두 번째 실행은 확인창 지연 때문에 중간 관찰기가 먼저 240초 제한에 도달하여 전 구간의 연속 표본을 확보하지 못했다. `run-2.json`의 관찰 시간 초과는 장비 실행의 도착 시간 초과가 아니다. 두 번째 결과는 `../research/verification/run-machine-verification/run-2-final.json`과 `run-complete.png`에 별도로 저장했다. 첫 실행의 297개 표본과 두 번째 최종 확인은 증거 범위가 다르다.

최종적으로 확인창이 없는 시험 탭을 닫고, 장비를 시험 도면 중심 `(12.5,12.5,0)`으로 복귀시켜 정지를 확인했다. 실제 원시 좌표는 중앙 원점 근처이며, 연결을 유지했다. 이 좌표 정렬은 이번 레이저 OFF 경로 시험용이다. 실제 시료 가공 전에는 정렬을 별도로 확인해야 한다. 최종 상태는 `../research/verification/run-machine-verification/final-center.json`에 저장했다.

이번 결과는 이 도면·속도·5구간의 실제 레이저 OFF 이동에 대한 확인이다. 복잡한 다른 도면, 장시간 반복, 레이저 가공 품질이나 외부 계측에 의한 위치 정확도를 검증한 것은 아니다. 이번 검증을 위해 실행기 코드는 변경하지 않았다.
