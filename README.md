# PromptShield

외부 회의록에 숨겨진 지시가 AI의 요약이나 도구 사용을 바꾸는지 재현하고, 입력 탐지와 도구 권한 검사의 효과를 비교하는 보안 프로젝트입니다.

**3주차 입력 탐지기**는 회의록의 의심 구절을 표시하고 위험 점수에 따라 요약을 진행하거나 검토를 위해 보류합니다. `screened`에서 입력 탐지를, `guarded-tools`에서 요약 저장과 전송 승인을 시연할 수 있습니다. 두 모드 모두 API 키 없이 `mock`으로 실행할 수 있습니다.

## 빠른 실행 — API 키 없이 점검

Python **3.11 이상**과 Git을 사용합니다. 이 단계는 Python 표준 라이브러리만 사용합니다. 아래 명령은 Windows PowerShell 기준이며 프로젝트 최상위 폴더에서 실행합니다.

```powershell
git clone --branch feat/input-risk-detection https://github.com/s-0y/PromptShield.git
cd PromptShield
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m agent.summarizer --provider mock --mode screened --dataset data/benign.jsonl --id benign-001
.\.venv\Scripts\python.exe -m evaluation.run_cases --provider mock --mode screened
```

기존 작업 폴더에서는 `git fetch origin` 후 `git switch feat/input-risk-detection`로 이동합니다. macOS/Linux에서는 위의 Python 실행 경로를 `.venv/bin/python`으로 바꿉니다. 가상환경을 활성화했다면 `python`으로 실행해도 됩니다.

화면에 `is_mock: true`와 `[MOCK]` 응답이 표시됩니다. 이 응답은 실행 흐름 확인용 고정 형식이며 실제 요약이나 공격 재현 결과가 아닙니다.

## 입력 위험 점수와 검토 보류

0~29점은 요약을 진행합니다. 30~69점은 경고를 기록한 뒤 요약하고, 70점 이상은 모델을 호출하기 전에 보류합니다. 단일 실행 화면의 `input_risk.findings`에서 탐지 이유와 원문 구간을 확인할 수 있습니다.

```powershell
.\.venv\Scripts\python.exe -m agent.summarizer --provider mock --mode screened --dataset data/benign_security.jsonl --id security-003
.\.venv\Scripts\python.exe -m agent.summarizer --provider mock --mode screened --dataset data/attacks.jsonl --id attack-001
.\.venv\Scripts\python.exe -m evaluation.run_cases --provider mock --mode screened --benign data/benign_security.jsonl
```

첫 명령은 보안 교육 문구를 인용한 정상 회의록에 경고를 남기고 요약을 진행합니다. 두 번째는 보류되어 `status=held`와 `model_called=false`가 표시됩니다. 마지막 명령은 정상 보안 회의록 3건과 기존 공격 예시 5건을 읽고 경고·보류 건수를 정답 라벨별로 집계합니다. [입력 탐지 규칙과 오탐 점검 결과](docs/input_detection.md)

## 같은 회의록으로 전송 승인 비교하기

아래 두 명령은 같은 공개 회의록을 읽고 요약을 저장합니다. 첫 실행은 승인 없이 전송을 요청하고, 두 번째 실행은 실행자가 이번 건의 전송을 명시적으로 승인합니다.

```powershell
.\.venv\Scripts\python.exe -m agent.summarizer --provider mock --mode guarded-tools --dataset data/benign.jsonl --id benign-001 --review-transfer request
.\.venv\Scripts\python.exe -m agent.summarizer --provider mock --mode guarded-tools --dataset data/benign.jsonl --id benign-001 --review-transfer approve
```

| 실행 설정 | 요약 저장 | 모의 전송 결과 |
|---|---|---|
| 전송 옵션 생략 | 허용 | 요청 없음 |
| `--review-transfer request` | 허용 | `approval_required`로 차단. 영수증 없음 |
| `--review-transfer approve` | 허용 | `review-inbox`를 대상으로 로컬 영수증 한 건 생성 |

화면의 `result_file`을 열면 `mock_tools.events`에 요청 주체, 도구명, 허용·차단 사유, 실행 여부가 순서대로 나옵니다. 승인 없는 실행에서도 요약은 저장되므로 전체 `status`는 `ok`입니다. 전송 여부는 `mock_tools.transfer_receipt`에서 확인합니다. 영수증은 해당 실행의 JSON에만 저장됩니다.

`guarded-tools`는 한 문서씩 실행합니다. 모델에 제공하는 도구는 `save_summary` 하나이고, 모델이 요청한 비공개 읽기나 전송은 실행자가 전송을 승인한 경우에도 차단됩니다. 승인된 전송은 요약을 저장한 뒤 프로그램이 처리합니다. 실제 모델로 실행하려면 아래 API 설정을 마치고 `--provider api`를 사용합니다. 선택한 모델이 Chat Completions 함수 호출을 지원해야 합니다.

## 실제 외부 API 연결

1. `.env.example`을 `.env`로 복사합니다.
2. `.env`의 모델명과 API 키를 설정합니다. OpenAI를 쓰는 경우 기본 주소를 사용하고, 다른 서비스는 아래 요청 형식을 지원하는 주소를 지정합니다.
3. 정상 문서 한 건부터 실행해 모델 연결과 응답을 확인합니다.

```powershell
Copy-Item .env.example .env
```

`.env`에서 수정할 항목:

```dotenv
PROMPTSHIELD_PROVIDER=api
PROMPTSHIELD_BASE_URL=https://api.openai.com/v1
PROMPTSHIELD_MODEL=계정에서_사용_가능한_정확한_모델_ID
PROMPTSHIELD_API_KEY=발급받은_API_키
PROMPTSHIELD_TIMEOUT_SECONDS=60
PROMPTSHIELD_MAX_COMPLETION_TOKENS=1024
PROMPTSHIELD_TEMPERATURE=
```

위의 모델명과 키는 설명용 자리표시자이므로 실제 값으로 바꿉니다. 키는 개인 `.env`에만 저장합니다. `.env`는 Git에서 제외됩니다. `OPENAI_API_KEY` 환경변수도 사용할 수 있으며, 이미 설정된 프로세스 환경변수는 `.env`보다 우선합니다.

```powershell
.\.venv\Scripts\python.exe -m agent.summarizer --provider api --dataset data/benign.jsonl --id benign-001
.\.venv\Scripts\python.exe -m agent.summarizer --provider api --dataset data/attacks.jsonl --id attack-001
```

API 모드에서는 선택한 문서와 요약 요청을 설정한 서비스로 전송하며, 사용량에 따른 비용이 발생할 수 있습니다. 코드가 보내는 요청은 `POST {BASE_URL}/chat/completions`이며 `model`, `messages`, `stream=false`, `max_completion_tokens`를 사용합니다. 해당 형식을 지원하는 서비스가 필요합니다. 모든 외부 API와 바로 호환되는 것은 아닙니다.

`PROMPTSHIELD_TEMPERATURE`를 비워 두면 요청에서 생략합니다. 모델이 지원하는 경우에만 값을 지정하고 실험 중에는 동일하게 유지합니다. 정확한 모델 스냅샷 ID를 사용할 수 있다면 고정해 기록합니다.

## 방어 문구 적용 여부 비교

- `baseline`: 기본 요약 지시와 문서를 전달합니다. 추가적인 문서 경계 방어 문구가 없습니다.
- `boundary`: 외부 문서를 JSON으로 구분하고, 문서 안의 지시를 따르지 말라는 문구를 추가합니다.

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_cases --provider api --mode baseline
.\.venv\Scripts\python.exe -m evaluation.run_cases --provider api --mode boundary
```

각 명령은 기본 데이터 10건에 대해 10번의 독립적인 요청을 보냅니다. 대화 이력은 사례 간 공유하지 않습니다. 공격 지시를 강제로 따르는 코드는 없으므로, `baseline`에서도 모델이 공격에 저항할 수 있습니다.

`screened`는 같은 `boundary` 메시지를 사용하며 모델 호출 전에 입력 위험을 평가합니다. 네 실험군의 방어 성능 비교는 후속 평가에서 진행합니다.

## 결과와 오류 확인

단일 실행은 `results/<run_id>/result.json`, 일괄 실행은 `results/<run_id>/results.jsonl`과 `summary.json`을 생성합니다. 실행마다 고유 폴더를 만들어 이전 결과를 보존합니다.

기록 항목은 샘플·라벨, 원문과 해시, 실제 전송 메시지, 프롬프트 모드·버전, 요청 모델과 응답 모델, 설정, 응답, 사용량, 처리 시간, 종료 사유, 오류입니다. 설정의 API 키와 HTTP 오류 응답 본문은 기록하지 않습니다. 결과에는 원문·응답이 포함되므로 `results/`는 Git에서 제외합니다.

- `status=ok`: 응답이 정상 종료됐다는 뜻입니다. 요약의 정확성이나 공격 실패를 뜻하지 않습니다.
- `status=incomplete`: 토큰 제한 등으로 응답이 완결되지 않았습니다.
- `screened`에서 입력 검사가 보류한 문서는 `status=held`가 됩니다. 검사가 정상적으로 끝났으므로 보류만으로는 명령의 종료 코드가 바뀌지 않습니다.
- `guarded-tools`에서 요약 저장을 완료할 수 없는 도구 요청이 차단되면 `status=blocked`가 기록되고 명령은 종료 코드 1을 반환합니다. 차단 사유는 `mock_tools.events`의 `reason`에서 확인합니다.
- `status=error`: 연결·인증·응답 형식 등의 오류입니다.
- `attack_success`와 `normal_task_success`는 아직 판정하지 않아 `null`입니다.
- 오류·미완료 응답이 있으면 명령은 종료 코드 1을 반환합니다. API 오류를 모의 응답으로 대체하거나 자동으로 재시도하지 않습니다.

실제 LLM 응답은 동일한 설정에서도 달라질 수 있습니다. 기록을 바탕으로 대표 사례를 반복 실행하고 [실험 절차](docs/baseline_agent.md)에 따라 검토합니다.

## 기존 요청 미리보기

기존 1주차 명령은 계속 네트워크 연결 없이 동작합니다. 기본 모드는 `baseline`으로 변경됐고, 이전처럼 경계 방어 문구를 포함하려면 `--mode boundary`를 지정합니다.

```powershell
.\.venv\Scripts\python.exe -m agent.llm_client --dataset data/benign.jsonl --id benign-001 --mode boundary
```

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

테스트는 모의 응답과 이 PC의 테스트 서버를 사용합니다. HTTP 요청 형식, 한글 응답, 오류 처리, 데모 문서 10건의 일괄 실행을 확인합니다. 도구 검증에는 문서 범위, 호출 인자, 중복 저장, 복수 호출의 일괄 거부, 승인 주체, 실행 기록까지 포함됩니다.

## 파일 구조

```text
agent/
  config.py          # .env와 환경변수 설정
  datasets.py        # JSONL 검증과 샘플 선택
  input_risk.py      # 입력 위험 점수, 탐지 이유, 원문 구간
  llm_client.py      # 실제 API 호출·모의 응답·요청 미리보기
  summarizer.py      # 단일 문서 실행과 결과 저장
  tools.py           # 문서별 모의 도구, 권한 검사, 실행 기록
evaluation/
  run_cases.py       # 정상·공격 사례 일괄 실행
tests/
  test_baseline.py   # 외부 유료 호출 없는 자동 검증
  test_mock_tools.py # 도구 정책과 승인별 결과 검증
  test_input_risk.py # 입력 탐지, 호출 보류, 오탐 집계 검증
data/
  benign.jsonl       # 정상 데모 5건
  attacks.jsonl      # 공격 데모 5건
  benign_security.jsonl # 오탐 점검용 정상 보안 회의록 3건
docs/
  project_goals.md   # 세부 목표·완료 기준
  threat_model.md    # 위협 모델
  baseline_agent.md  # 설정·실험·결과 해석
  input_detection.md # 위험 점수, 보류, 오탐 결과 해석
```

## 6주 개요

| 주차 | 목표 | 주요 결과물 |
|---|---|---|
| 1 | 이론 조사, 환경 구성, 공격 시나리오 설계 | 기본 구조, 데모 문서 10건, 위협 모델 |
| 2 | 기본 요약 에이전트와 도구 시연 | 모델 연결, 응답 기록, 모의 도구와 실행 전 권한 검사 |
| 3 | 입력 위험 탐지 | 규칙 탐지·위험 점수·오탐 점검 |
| 4 | 실행 권한 검사와 통합 | 도구·인자·경로·승인 검사 |
| 5 | 데이터 확장과 비교 평가 | 공격 60건·정상 40건, A/B/C/D 비교 |
| 6 | 대시보드와 최종 정리 | 시연, 보고서, 발표자료 |

공격 4유형, 방어 3요소, 평가 지표 5개의 상세 범위는 [프로젝트 목표](docs/project_goals.md)를 참고합니다.
