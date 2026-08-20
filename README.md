# 충북 지방소멸대응기금 성과분석 API

집행률이 아니라 **청년 순이동률**로 기금 성과를 평가하는 백엔드. 프론트엔드 목업
(https://impact-advisor-ai.lovable.app/)에 실제 데이터를 공급한다.

## 계층

| 계층 | 내용 | LLM |
|---|---|---|
| Layer 1 분석 엔진 | 패널 집계, 기금 지표, 사전계산 분석 아티팩트, 근거 검색, 규칙 기반 제안 | 호출 안 함. 같은 입력 → 같은 출력 |
| Layer 2 에이전트 | 자연어 질문 라우팅과 서술 | 선택. 비활성이면 규칙 기반으로 동작 |

Layer 2는 숫자를 만들지 않는다. 서술에 등장한 모든 숫자는 Layer 1 응답에 실재해야 하며,
`POST /api/chat` 응답의 `numeric_guard` 가 이를 검증한다. 검증에 걸린 답변은 폐기되고
수치 없는 안내 문장으로 대체된다.

## 실행

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
cp .env.example .env
uv run python scripts/build_artifacts.py     # data/artifacts/ 생성 (최초 1회)
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                                # 104 tests (PDF가 있으면 107)
```

> **사업내역서 PDF는 저장소에 없다.** 담당 공무원 실명이 들어 있어 제외했다.
> 팀 내부에서 받아 `data/raw/evidence/pdf/` 에 넣으면 검색 인덱스가 자동으로 확장되고,
> PDF를 전제한 테스트 3개도 함께 실행된다. PDF가 없어도 서버는 정상 기동하며 근거 검색은
> 등록부(`project_evidence_register_ko.md`) 3건만으로 동작한다.

- OpenAPI 문서: http://localhost:8000/docs (프론트는 이 문서만 보고 붙일 수 있다)
- 헬스체크: http://localhost:8000/api/health → `panel_rows: 1056`

## 응답 봉투

```json
{ "data": {}, "meta": { "source": "...", "as_of": "2024-12", "data_status": "actual", "notes": [] } }
```

`data_status` 는 세 가지뿐이다.

| 값 | 뜻 |
|---|---|
| `actual` | 원자료에 실재하는 값 |
| `unavailable` | 요청 범위에 데이터가 없음 (예: 2025년) |
| `derived` | 원자료로부터 규칙에 따라 계산한 값 |

목업 값을 뜻하는 상태는 없다. 에러는 `{"error": {"code", "message", "field", "allowed_values"}}` 구조로 통일했고,
없는 지역·지표·기금을 요청하면 `allowed_values` 에 사용 가능한 값이 함께 온다.

## 엔드포인트

| 화면 | 메서드 | 경로 |
|---|---|---|
| 공통 | GET | `/api/health`, `/api/meta/regions`, `/api/meta/metrics`, `/api/meta/funds` |
| 기금 대시보드 | GET | `/api/funds/{fund_id}/summary?year=2024`, `/regions?year=2024`, `/trend` |
| 인과분석 | GET | `/api/panel/timeseries`, `/api/panel/group-timeseries`, `/api/analysis/did`, `/api/analysis/validation`, `/api/analysis/diagnostics` |
| 제안 | GET | `/api/evidence/projects`, `/api/evidence/search?q=&grade=&purpose=`, `/api/proposal?year=2026` |
| 질문 입력 | POST | `/api/chat` |

`fund_id` 는 현재 `local-extinction` 1종이다.

## 목업과 실제 데이터가 다른 지점 (프론트 확인 필요)

| 항목 | 목업 화면 | 실제 API |
|---|---|---|
| 인과분석 설계 | 처치 3개(제천·괴산·영동) vs 비교 3개(단양·보은·옥천) | **처치 6개** (제천·보은·옥천·영동·괴산·단양) vs **비교 5개** (청주·충주·증평·진천·음성) |
| 효과 크기 | +2.3%p, p<0.05 | **+0.9496명/천명, p=0.4631 — 유의하지 않음**. `significance.is_significant: false` |
| 대시보드 연도 | 2025 | 패널은 2024까지. 2025 요청은 `data_status: unavailable` 로 응답하며 값을 만들지 않는다 |

효과 크기의 단위는 `%p` 가 아니라 `명/천명` 이다. 유의성 표기는
`/api/analysis/did` 의 `significance.is_significant` 와 `significance.label_ko` 로 결정한다.

## 데이터 규칙 (수치가 이상해 보일 때 먼저 볼 것)

- **기금 금액은 지역-연도 중복 제거 후 합산한다.** 패널은 연도값을 12개월에 반복 결합해 두어,
  월별 합산하면 정확히 12배가 된다. 집계는 `Panel.fund_year_frame()` 만 사용한다.
- **1인당 기금 지표는 연말(12월) 인구를 분모로 재계산한 파생값이다.** 원본 컬럼은 분모가 월별
  인구라 지역-연도 안에서도 값이 달라, 임의의 달을 집으면 값이 흔들린다.
- **비교군 5개 시군은 배분액이 0**이라 집행률이 정의되지 않는다(`null`). 0%가 아니다.
- **`employment_insured_yoy_pct` 의 2017년 132행은 구조적 결측**이며 보간하지 않는다. 보간된
  CSV는 적재 단계에서 거부된다.
- **집행률은 성과 지표가 아니다.** 투입 진행률이며, 성과는 `youth_net_migration_rate_per_1000` 로 본다.
- **그룹 평균은 지역 단순평균**이다(인구 가중 아님). `meta.notes` 에 매번 명시된다.

## 분석 아티팩트

`/api/analysis/*` 는 추정을 수행하지 않고 `data/artifacts/` 의 JSON을 읽어 반환한다.
모델링 담당자가 새 결과를 주면 파일만 교체하면 되고, **재기동 없이 반영된다**(요청 시 mtime 확인).

- 스키마: `app/schemas/artifacts.py` (`DidArtifact`, `ValidationArtifact`)
- 파일: `data/artifacts/did_twfe_v1.json`, `data/artifacts/oot_validation_v1.json`
- 변환 스크립트: `scripts/build_artifacts.py` (baseline JSON + OOT CSV → v1)

스키마에 맞지 않는 아티팩트는 500 응답으로 거부되며, 어긋난 필드 목록이 `details.violations` 에 담긴다.
`is_significant` 가 p값·유의수준과 어긋나면 적재 자체가 실패한다 — 유의하지 않은 결과를 유의한
것으로 표기한 아티팩트는 서비스에 들어올 수 없다.

## 근거 등급

`project_evidence_register_ko.md` 의 판정을 그대로 따른다.

| 등급 | 기준 | 사용 |
|---|---|---|
| A | 기금액·사업기간이 있고 2022~2024 평가창 내 추진 기록 확인 | 사례분석·착수시점 후보 |
| B | 기금액·사업기간은 있으나 평가창 내 기록 불충분 | 설명·근거 카드 |
| C | 사업 시작이 2025년 이후 | **2017~2024 효과추정 제외**, 2026 제안 근거로만 |

`/api/evidence/search?purpose=performance_2017_2024` 는 등급 C를 자동으로 제외한다.
검색은 BM25(키워드) + 문자 2-gram 코사인(벡터)을 절반씩 섞은 하이브리드이며, 외부 임베딩 API를
쓰지 않아 오프라인에서도 결정적으로 동작한다. 파싱 결과는 `data/index/` 에 캐싱되고 원본 파일
지문이 바뀔 때만 다시 만든다.

## 차년도 제안

`/api/proposal?year=2026` 은 규칙 기반이다. 규칙 전문은 `app/services/proposal.py` 상단 주석에 있고,
응답의 `basis.rules` 로도 나간다. `basis.is_causal_estimate` 는 항상 `false` 다 — 1차 DID가
유의하지 않으므로 기술통계·진단 지표에 근거한 참고안임을 응답에서 명시한다.

순위는 기금 배분 대상 6개 시군 안에서만 매기고, 비배분 5개 시군은 진단만 제공한다.

## 자연어 질의

```bash
curl -X POST localhost:8000/api/chat -H 'content-type: application/json' \
  -d '{"question": "제천시 집행률"}'
```

응답에 라우팅 결과(`routing`), 호출한 엔드포인트(`called_endpoints`), 그 결과(`tool_results`),
서술(`answer`), 이동 화면(`navigation.screen`), 인용(`citations`), 수치 검증(`numeric_guard`)이 담긴다.

의도: `fund_execution`, `metric_timeseries`, `region_comparison`, `causal_analysis`,
`evidence_search`, `proposal`, `out_of_scope`.

`navigation.screen` 이 계약이고 `path` 는 제안이다. 프론트 라우팅 경로는 프론트가 정한다.

`LLM_ENABLED=false` 면 규칙 기반 라우터·서술로 동작한다. 응답은 결정적이며 API 키가 없어도
전 과정이 돌아간다. 발표 당일 네트워크 문제로 데모가 죽지 않게 하기 위한 설계다.

## 프로젝트 구조

```
app/
  config.py            설정(.env)
  errors.py            통일 에러 응답
  data/                패널 로더·계약 검증, 지표 카탈로그, 근거 문서 파싱
  schemas/             응답 봉투, 기금, 아티팩트 스키마
  services/            Layer 1 계산 + Layer 2 라우팅·서술·수치 검증
  routers/             엔드포인트
data/
  raw/                 원자료 (수정하지 않는다)
  artifacts/           분석 결과 v1 아티팩트
  index/               근거 검색 캐시 (git 제외)
scripts/build_artifacts.py
tests/
```
