# Windows 휴대용 실행 및 폴더 정리 검증

검증일: 2026-10-27. 이 기록은 소프트웨어 배포·실행 검증이며, 새 PC의 실물 드라이버와 ESP300 응답을 확인한 기록은 아닙니다.

## 구현

- `dwg-esp300-launch.cmd`: 사용자 PC의 Conda 경로 대신 폴더 내 Python 사용. 소스 실행 시 실행 환경이 없으면 자동 준비.
- `runtime/`: Python 3.12.10 x64 앱 내장 배포와 `requirements.txt`에 고정된 라이브러리. 설치 관리자와 관리자 권한 없이 사용.
- `/api/serial/ports`, Find Windows ports: 포트를 열지 않고 COM 목록 표시. WSL 설치·USB 전달·자동 장비 검사는 수행하지 않음.
- WSL은 선택 경로. WSL 실행 파일이 없는 환경에서도 종료 도구 작동.
- 기본 도면과 예제 스크립트는 저장소 상대 경로 사용. OpenCV 4/5의 로그 설정 차이 처리.
- `build-portable.cmd`: 필요한 앱 파일만 명시적으로 포함하고, 파일별 SHA-256 manifest 및 ZIP SHA-256 생성.

## 결과

- 관련 unittest 55개 실행: 54개 통과, Linux `/proc` 전용 1개 제외.
- 기존 standalone 영상/스캔 보조 검사 3개 스크립트 모두 `OK`.
- JavaScript 문법 검사 및 `git diff --check` 통과.
- 포함된 Aspose.CAD로 기존 20 mm 선 DWG를 DXF로 변환 성공.
- ZIP을 한글·공백이 있는 새 경로에 풀어 전체 manifest 해시 대조.
- PATH에서 시스템 Python, Conda, py, WSL, usbipd를 찾을 수 없도록 하고 USERPROFILE을 빈 경로로 바꿔 CMD 실행 검증.
- `-Check`, HTTP 서버 시작, Windows 포트 목록 API, 샘플 DXF, 예제 모션, COM999를 이용한 Dry run, 서버 종료, WSL 없는 종료 도구 모두 통과. 실제 COM999를 열지 않음.

재현: 소스 폴더에서 `build-portable.cmd` 실행 후 `runtime\python.exe tools\verify_portable.py`. 이 검증은 임시 압축 해제 폴더를 `outputs/`에 남깁니다. 테스트가 성공하면 해당 임시 폴더를 제거해도 됩니다. 상세 결과는 로컬 `outputs/portable-verification.json`에 남습니다.

새 PC 실물 확인: Windows 포트를 선택하고 Test hardware link로 실제 `VE` 응답 확인. 이 검증에서는 실물 포트·카메라를 열거나 모터를 움직이지 않았습니다. 카메라 인덱스, 드라이버 호환성, 기계 축 배정·방향, 가공 품질은 해당 장비에서 확인해야 합니다.

## 정리

일반 사용자 파일은 모두 `.git`이 있는 `dwg-to-esp300-lab-code/` 아래로 모았습니다. FLW의 `.codex/` 환경 설정은 유지했습니다. 원본 CAD·논문·실험 기록은 `research/`, 기존 PDF/PPTX 설명 자료는 `docs/reference/`, 샘플 DXF는 `drawings/`에 있습니다. 과거 문서는 당시 동작 설명이므로 새 실행·연결 절차는 `quick-start.ko.md`를 우선합니다.

이전 업로드·자동 생성물·스크린샷·캐시·중복 안내 300개는 약 29 MiB의 복구용 ZIP으로 보관하고 개별 파일을 제거했습니다. 설치된 Conda와 별개의 153 MiB Miniconda 설치 파일도 제거했습니다. Git 이력은 유지했으며, 커밋·푸시하지 않았습니다. 실행 환경·배포본·업로드·산출물·정리 보관본은 Git에서 제외했습니다.

기존 8768 서버는 장비 작업 중이 아님을 확인하고 자체 종료 API로 종료하여 외부 출력 폴더의 잠긴 로그를 옮겼습니다. 실물 장비 제어 명령은 보내지 않았습니다.
