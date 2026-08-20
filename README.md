# 충북 지방소멸대응기금 성과분석 API

집행률이 아니라 **청년 순이동률**로 기금 성과를 평가하는 백엔드. 프론트엔드 목업(https://impact-advisor-ai.lovable.app/)에 실제 데이터 공급.

---

## 1. 계층 구조

| 계층 | 내용 | LLM |
|---|---|---|
| Layer 1 분석 엔진 | 패널 집계, 기금 지표, 사전계산 분석 아티팩트, 근거 검색, 규칙 기반 제안 | 호출 없음. 같은 입력이면 같은 출력 |
| Layer 2 에이전트 | 자연어 질문 라우팅과 서술 | 선택. 비활성 시 규칙 기반 동작 |

- Layer 2는 숫자를 생성하지 않는 서술 계층
- 서술에 등장하는 모든 숫자는 Layer 1 응답에 실재해야 하며, 수치 가드가 매 응답 검증
- 검증 실패 시 해당 서술 폐기 후 수치 없는 안내 문장으로 대체

---

## 2. 실행

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
cp .env.example .env
uv run python scripts/build_artifacts.py     # data/artifacts/ 생성 (최초 1회)
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                                # 107개 (PDF가 있으면 110개)
```

- OpenAPI 문서는 http://localhost:8000/docs (프론트는 이 문서만으로 연동 가능)
- 헬스체크는 http://localhost:8000/api/health → `panel_rows: 1056`
- 서버 종료는 `pkill -f "uvicorn app.main"`

### 사업내역서 PDF

- 담당 공무원 실명 포함으로 저장소에서 제외
- 팀 내부에서 받아 `data/raw/evidence/pdf/`에 배치하면 검색 인덱스 자동 확장 및 관련 테스트 3개 추가 실행
- PDF가 없어도 서버는 정상 기동하며, 근거 검색은 등록부(`project_evidence_register_ko.md`) 3건으로 동작

---

## 3. 응답 규칙

### 공통 응답 구조

```json
{ "data": {}, "meta": { "source": "...", "as_of": "2024-12", "data_status": "actual", "notes": [] } }
```

### data_status

| 값 | 뜻 |
|---|---|
| `actual` | 원자료에 실재하는 값 |
| `unavailable` | 요청 범위에 데이터 없음 (예시로 2025년) |
| `derived` | 원자료로부터 규칙에 따라 계산한 값 |

- 목업 값을 뜻하는 상태는 부재
- 에러는 `{"error": {"code", "message", "field", "allowed_values"}}` 구조로 통일
- 없는 지역·지표·기금 요청 시 `allowed_values`에 사용 가능한 값 동봉

---

## 4. 엔드포인트

| 화면 | 메서드 | 경로 |
|---|---|---|
| 공통 | GET | `/api/health`, `/api/meta/regions`, `/api/meta/metrics`, `/api/meta/funds` |
| 기금 대시보드 | GET | `/api/funds/{fund_id}/summary?year=2024`, `/regions?year=2024`, `/trend` |
| 인과분석 | GET | `/api/panel/timeseries`, `/api/panel/group-timeseries`, `/api/analysis/did`, `/api/analysis/validation` |
| 제안 | GET | `/api/evidence/projects`, `/api/evidence/search?q=&grade=&purpose=`, `/api/proposal?year=2026` |
| 질문 입력 | POST | `/api/chat` |

`fund_id`는 현재 `local-extinction` 1종.

---

## 5. 목업과 실제 데이터의 차이 (프론트 확인 필요)

| 항목 | 목업 화면 | 실제 API |
|---|---|---|
| 인과분석 설계 | 처치 3개(제천·괴산·영동) vs 비교 3개(단양·보은·옥천) | **처치 6개**(제천·보은·옥천·영동·괴산·단양) vs **비교 5개**(청주·충주·증평·진천·음성) |
| 효과 크기 | +2.3%p, p<0.05 | **+0.9496명/천명, p=0.4631로 유의하지 않음.** `significance.is_significant: false` |
| 대시보드 연도 | 2025 | 패널은 2024까지. 2025 요청은 `data_status: unavailable`로 응답하며 값 생성 없음 |

- 효과 크기의 단위는 `%p`가 아니라 `명/천명`
- 유의성 표기는 `/api/analysis/did`의 `significance.is_significant`와 `significance.label_ko`로 결정

---

## 6. 데이터 규칙 (수치가 이상해 보일 때 먼저 확인)

- **기금 금액은 지역-연도 중복 제거 후 합산.** 패널이 연도값을 12개월에 반복 결합해 두어 월별 합산 시 정확히 12배. 집계는 `Panel.fund_year_frame()`만 사용
- **1인당 기금 지표는 연말(12월) 인구를 분모로 재계산한 파생값.** 원본 컬럼은 분모가 월별 인구라 지역-연도 안에서도 값이 변동
- **비교군 5개 시군은 배분액이 0이라 집행률이 정의되지 않음(`null`).** 0%가 아님
- **`employment_insured_yoy_pct`의 2017년 132행은 구조적 결측.** 보간하지 않으며, 보간된 CSV는 적재 단계에서 거부
- **집행률은 성과 지표가 아닌 투입 진행률.** 성과는 `youth_net_migration_rate_per_1000`으로 측정
- **그룹 평균은 인구 가중이 아닌 지역 단순평균.** `meta.notes`에 매번 명시

---

## 7. 자연어 질의

```bash
curl -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"question": "제천시 집행률"}'
```

### 응답 구성

| 필드 | 내용 |
|---|---|
| `routing` | 라우팅 결과 |
| `called_endpoints` | 호출한 엔드포인트 |
| `tool_results` | 호출 결과 |
| `answer` | 서술 |
| `navigation.screen` | 이동 화면 |
| `citations` | 인용 |
| `numeric_guard` | 수치 검증 결과 |

- 의도는 `fund_execution`, `metric_timeseries`, `region_comparison`, `causal_analysis`, `evidence_search`, `proposal`, `out_of_scope` 7종
- `navigation.screen`이 계약이고 `path`는 제안. 프론트 라우팅 경로는 프론트가 결정
- `LLM_ENABLED=false`면 규칙 기반 라우터·서술로 동작. 응답이 결정적이며 API 키 없이 전 과정 구동
- 발표 당일 네트워크 장애로 데모가 중단되지 않게 하기 위한 설계

### 수치 가드

- 서술에 등장하는 숫자 중 도구 결과에 없는 값이 있으면 해당 서술 전체 폐기
- 단, **질문에 등장한 숫자를 되받아 인용하는 것은 허용**. "2025년 집행률" 질문에 "2025년 데이터는 없습니다"로 답하는 경우가 이에 해당
- 되받은 숫자는 `numeric_guard.numbers_echoed_from_question`에 기록해 출처 추적 가능
- 도구 결과에 없는 수치를 새로 주장하는 경우는 기존대로 차단

### 서술 프롬프트 규칙

- 도구 결과의 단위를 그대로 사용. 4,093백만원을 40.93억원으로 바꾸는 환산 금지
- 반올림은 소수 둘째 자리까지 허용. 63.953125%가 아니라 63.95%로 표기
- 차이·합계 등 새로운 계산 금지
- 묻지 않은 연도의 선제 언급 금지

> **프롬프트에 예시 숫자를 적을 때 주의.** 프롬프트 본문에 적힌 숫자를 LLM이 그대로 인용하면 도구 결과에 없는 숫자로 판정되어 답변이 폐기됨. 실제로 규칙 5번에 박혀 있던 `2025` 때문에 정상 응답이 폐기되던 사례 발생.

---

## 8. 평가

```bash
uv run python evals/run_eval.py
```

- 표준 질의 16건을 실행해 라우팅·서술·수치 검증 결과 채점
- 케이스별 기대 정답(골든)은 `evals/` 아래 정의
- 현재 13/16 통과

### 알려진 한계

| 항목 | 내용 |
|---|---|
| 판정 기준 | `narrator != "llm"`이면 무조건 FAIL 처리. 가드가 LLM 서술을 걸러 규칙 서술로 내려가는 것은 설계상 정상 동작이므로, LLM 호출 실패와 구분 필요. 현재 두 경우가 동일 처리되어 일부 케이스 점수가 실행마다 변동 |
| 기금 지표 비교 | `region_comparison` 경로가 패널 지표만 처리하고 기금 집행률 미지원. 라우팅 문제가 아닌 비교 경로의 기능 공백 |
| 골든 기대값 | "청년들 어디서 제일 많이 빠져나갔어?"의 기대값은 영동이나, 2024년 데이터 기준 전출률 1위는 괴산군(25.52명/천명), 전출 인원 1위는 청주시(52,684명). 기대값 재확인 필요 |

---

## 9. 분석 아티팩트

- `/api/analysis/*`는 추정을 수행하지 않고 `data/artifacts/`의 JSON을 읽어 반환
- 모델링 담당자가 새 결과를 전달하면 파일 교체만으로 반영. **재기동 불필요**(요청 시 mtime 확인)

| 구분 | 경로 |
|---|---|
| 스키마 | `app/schemas/artifacts.py` (`DidArtifact`, `ValidationArtifact`) |
| 파일 | `data/artifacts/did_twfe_v1.json`, `data/artifacts/oot_validation_v1.json` |
| 변환 스크립트 | `scripts/build_artifacts.py` (baseline JSON + OOT CSV → v1) |

- 스키마에 맞지 않는 아티팩트는 500 응답으로 거부되며, 어긋난 필드 목록은 `details.violations`에 수록
- `is_significant`가 p값·유의수준과 어긋나면 적재 자체가 실패. 유의하지 않은 결과를 유의한 것으로 표기한 아티팩트는 서비스 진입 불가

---

## 10. 근거 등급

`project_evidence_register_ko.md`의 판정을 그대로 적용.

| 등급 | 기준 | 사용 |
|---|---|---|
| A | 기금액·사업기간이 있고 2022~2024 평가창 내 추진 기록 확인 | 사례분석·착수시점 후보 |
| B | 기금액·사업기간은 있으나 평가창 내 기록 불충분 | 설명·근거 카드 |
| C | 사업 시작이 2025년 이후 | **2017~2024 효과추정 제외.** 2026 제안 근거로만 사용 |

- `/api/evidence/search?purpose=performance_2017_2024`는 등급 C 자동 제외
- 검색은 BM25(키워드)와 문자 2-gram 코사인(벡터)을 절반씩 섞은 하이브리드
- 외부 임베딩 API를 쓰지 않아 오프라인에서도 결정적으로 동작
- 파싱 결과는 `data/index/`에 캐싱되며 원본 파일 지문이 바뀔 때만 재생성

---

## 11. 차년도 제안

- `/api/proposal?year=2026`은 규칙 기반
- 규칙 전문은 `app/services/proposal.py` 상단 주석에 수록되며 응답의 `basis.rules`로도 반환
- `basis.is_causal_estimate`는 항상 `false`. 1차 DID가 유의하지 않으므로 기술통계·진단 지표에 근거한 참고안임을 응답에서 명시
- 순위는 기금 배분 대상 6개 시군 안에서만 산정하고, 비배분 5개 시군은 진단만 제공

---

## 12. 테스트

- 네트워크 없이 결정적으로 동작. `conftest.py`에서 테스트 세션의 LLM을 강제 비활성화
- `.env`에 `LLM_ENABLED=true`가 있어도 실제 API 호출 없음
- 107개 통과. 사업내역서 PDF가 있으면 PDF 전제 테스트 3개가 추가되어 110개

---

## 13. 프로젝트 구조

```
app/
  config.py            설정(.env)
  errors.py            통일 에러 응답
  data/                패널 로더·계약 검증, 지표 카탈로그, 근거 문서 파싱
  schemas/             공통 응답 구조, 기금, 아티팩트 스키마
  services/            Layer 1 계산 + Layer 2 라우팅·서술·수치 검증
  routers/             엔드포인트
data/
  raw/                 원자료 (수정 금지)
  artifacts/           분석 결과 v1 아티팩트
  index/               근거 검색 캐시 (git 제외)
evals/
  run_eval.py          표준 질의 평가 러너
scripts/build_artifacts.py
tests/
```
