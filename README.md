# PromptShield

간접 프롬프트 인젝션 공격을 재현·탐지하고 여러 방어 단계를 비교하기 위한 6주 보안 프로젝트입니다. AI가 회의록 같은 외부 문서를 요약할 때, 문서 안의 공격자 지시를 사용자 지시로 잘못 받아들이는 상황을 연구합니다.

현재 저장소는 **1주차 스캐폴딩**입니다. 네트워크 요청, 실제 모델 호출, 도구 실행, 탐지 엔진은 포함하지 않습니다. `agent/llm_client.py`는 향후 모델 연동에 사용할 메시지를 로컬에서 만들고 출력합니다. 메시지에 문서를 데이터로 표시하는 것만으로 공격이 차단되지는 않습니다.

## 6주 개요

| 주차 | 목표 | 주요 결과물 |
| --- | --- | --- |
| 1 | 이론 조사, 환경 구성, 공격 시나리오 설계 | 기본 구조, 정상·공격 예시 각 5개, 위협 모델 |
| 2 | 취약한 문서 요약 에이전트 구현과 공격 재현 | 통제된 실험 환경, 공격 성공 조건 검증 |
| 3 | 입력 탐지 시스템 구현 | 규칙·분류 기반 탐지 및 탐지율 측정 |
| 4 | 도구 권한 검사와 다중 방어 통합 | 권한 정책, 차단 및 기록 흐름 |
| 5 | 데이터셋 확장과 성능 평가 | 공격 성공률, 탐지율, 오탐률 비교 |
| 6 | 대시보드와 최종 결과 정리 | 시연 화면, 분석 보고서 |

## 파일 구조

```text
PromptShield/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
├── agent/
│   └── llm_client.py
├── data/
│   ├── benign.jsonl
│   └── attacks.jsonl
└── docs/
    └── threat_model.md
```

## 설치 및 실행

Python 3.10 이상을 사용합니다. 1주차 코드는 표준 라이브러리만 사용하므로 별도 패키지 설치가 필요하지 않습니다.

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
python -m agent.llm_client --dataset data/benign.jsonl --id benign-001
python -m agent.llm_client --dataset data/attacks.jsonl --id attack-001
```

명령은 모델에 보내기 전의 메시지를 JSON으로 출력합니다. 실제 LLM 호출이나 공격 성공 판정은 수행하지 않습니다. JSONL은 한 줄에 JSON 객체 하나이며, `id`와 `text` 필드를 포함합니다.

## 실험 범위

문서 요약 요청이 정상 작업입니다. 공격자는 요약 대상인 외부 문서의 본문만 바꿀 수 있다고 가정합니다. `data/`의 예시는 합성 데모 데이터이며 실제 비밀 정보나 자격 증명을 포함하지 않습니다. 공격 성공 조건과 향후 방어 평가 방법은 [위협 모델](docs/threat_model.md)에 정리했습니다.
