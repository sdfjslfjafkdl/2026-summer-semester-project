# 충북 지방소멸대응기금 성과분석 API

집행률이 아니라 **청년 순이동률**로 기금 성과를 평가하는 백엔드입니다.
이 문서는 **프론트 연동용**입니다. 백엔드 내부 설계는 [docs/backend.md](docs/backend.md)를 보세요.

## 서버 주소

| | |
|---|---|
| **API 베이스** | `https://2026-summer-semester-project-production.up.railway.app` |
| **API 문서 (Swagger)** | [/docs](https://2026-summer-semester-project-production.up.railway.app/docs) ← 모든 엔드포인트를 여기서 바로 호출해볼 수 있습니다 |
| **헬스체크** | [/api/health](https://2026-summer-semester-project-production.up.railway.app/api/health) |

이미 배포되어 돌아가고 있습니다. 로컬에 서버를 띄우지 않아도 바로 붙일 수 있습니다.

```bash
curl -s https://2026-summer-semester-project-production.up.railway.app/api/health
# {"data":{"status":"ok","panel_rows":1056,...},"meta":{...}}
```

CORS는 `https://impact-advisor-ai.lovable.app`을 허용해 두었습니다. 다른 도메인(미리보기 주소 등)에서
호출하는데 CORS 에러가 나면 알려주세요. 환경변수만 고치면 됩니다.

---

## 응답은 항상 같은 모양

```json
{
  "data": { },
  "meta": { "source": "...", "as_of": "2024-12", "data_status": "actual", "notes": [] }
}
```

`meta.data_status` 세 가지만 보면 됩니다.

| 값 | 화면에서 할 일 |
|---|---|
| `actual` | 그대로 표시 |
| `derived` | 그대로 표시 (계산된 값) |
| `unavailable` | **"데이터 없음"으로 표시.** `data`의 값들이 `null`입니다 |

에러는 이렇게 옵니다. `allowed_values`가 있으면 드롭다운 채우는 데 쓰면 됩니다.

```json
{ "error": { "code": "unknown_region", "message": "...", "field": "regions", "allowed_values": ["제천시", ...] } }
```

---

## 엔드포인트

### 공통 (드롭다운·초기 로딩용)

| 경로 | 무엇을 주나 |
|---|---|
| `GET /api/health` | 서버 상태, 데이터 행 수, LLM 켜짐 여부 |
| `GET /api/meta/regions` | 11개 시군 목록 + 처치군/비교군 구분 |
| `GET /api/meta/metrics` | 지표 목록 (키, 한글 라벨, 단위, 정의) |
| `GET /api/meta/funds` | 기금 목록. 현재 `local-extinction` 1종 |

### 화면 1 — 기금 대시보드

| 경로 | 무엇을 주나 |
|---|---|
| `GET /api/funds/local-extinction/summary?year=2024` | 총 배분액·집행액·집행률, 전년 대비 증감 |
| `GET /api/funds/local-extinction/regions?year=2024` | 시군별 배분액·집행액·집행률·사업수·1인당 배분액 (집행률 내림차순) |
| `GET /api/funds/local-extinction/trend` | 2022~2024 연도별 집행률 추이 |

```bash
curl -s "$BASE/api/funds/local-extinction/summary?year=2024"
```

### 화면 2 — 인과분석

| 경로 | 무엇을 주나 |
|---|---|
| `GET /api/panel/group-timeseries?freq=year` | 처치군 평균 vs 비교군 평균 두 계열 + `treatment_start_period`(세로선 위치) |
| `GET /api/panel/timeseries?regions=제천시&metric=...&freq=month` | 시군별 지표 시계열 |
| `GET /api/analysis/did` | 추정 효과, p값, 신뢰구간, **유의성 판정** |
| `GET /api/analysis/diagnostics` | 강건성 검증(여러 사양, 부트스트랩 p값, 평행추세) |
| `GET /api/analysis/validation` | 시간외 검증(예측 오차) |

```bash
curl -s "$BASE/api/panel/group-timeseries?metric=youth_net_migration_rate_per_1000&freq=year"
```

### 화면 3 — 차년도 제안

| 경로 | 무엇을 주나 |
|---|---|
| `GET /api/proposal?year=2026` | 시군별 우선순위·권장 사업유형·배분 방향·근거 문장·근거 문서 |
| `GET /api/evidence/projects` | 등록 사업 목록과 근거 등급(A/B/C) |
| `GET /api/evidence/search?q=청년 주거` | 근거 문서 검색 (사업명, 등급, 원문 발췌, 쪽번호) |

### 화면 4 — 자연어 질문

| 경로 | 무엇을 주나 |
|---|---|
| `POST /api/chat` | 답변 문장 + 이동할 화면 + 인용 출처 |

```bash
curl -X POST "$BASE/api/chat" -H 'content-type: application/json' \
  -d '{"question": "제천시 집행률"}'
```

응답에서 화면이 쓸 것:

| 필드 | 용도 |
|---|---|
| `answer` | 말풍선에 표시할 문장 |
| `navigation.screen` | 이동할 화면 (`fund_dashboard` / `causal_analysis` / `evidence` / `proposal` / `chat`) |
| `navigation.params` | 그 화면에 넘길 파라미터 (연도, 지역 등) |
| `citations` | "출처" 표시용 |
| `routing.intent` | 어떤 질문으로 이해했는지 (디버깅용) |

### 화면 5 — 투자계획서 작성 (신규)

계획서 **완성본이 아니라 초안**을 만듭니다. 데이터로 채울 수 있는 항목만 채우고 나머지는
"담당자 작성 필요" 구획으로 남깁니다.

| 경로 | 무엇을 주나 |
|---|---|
| `POST /api/plan/draft` | `{"region":"제천시","year":2026}` → 초안 생성, `plan_id` 반환 |
| `GET /api/plan/{plan_id}` | 27개 항목의 현재 상태 + 버전 이력 |
| `POST /api/plan/{plan_id}/sections/{section_id}` | 담당자가 특정 항목 채우기 |
| `POST /api/plan/{plan_id}/revise` | 자연어 수정 지시 → 변경 요약 + diff |
| `GET /api/plan/{plan_id}/summary` | 비전문가용 5문장 요약 + 빈 필수 항목 목록 |
| `POST /api/plan/{plan_id}/export` | `{"format":"docx"}` → **파일 다운로드** (봉투 아님) |

각 항목의 `fill_mode`로 UI를 나누면 됩니다.

| `fill_mode` | 화면 표시 |
|---|---|
| `auto` | 이미 채워짐 (읽기 전용으로 보여주면 됨) |
| `assisted` | 초안이 들어 있음. 담당자가 보완하면 문장으로 다듬어짐 |
| `manual` | 비어 있음. `guidance.writing_guide`를 안내문으로 띄우고 입력받기 |

진행률은 `progress`에 있습니다 (`auto_filled`, `awaiting_human`, `completion_pct`).

```bash
# 초안 만들고 docx 받기
PID=$(curl -s -X POST "$BASE/api/plan/draft" -H 'content-type: application/json' \
  -d '{"region":"제천시","year":2026}' | jq -r .data.plan_id)

curl -X POST "$BASE/api/plan/$PID/export" -H 'content-type: application/json' \
  -d '{"format":"docx"}' -o 계획서_초안.docx
```

> export는 JSON이 아니라 파일이 옵니다. 프론트에서는 `blob`으로 받아 다운로드시키면 됩니다.
> 알림 메시지는 `X-Plan-Notes` 응답 헤더에 들어갑니다.

---

## 붙이기 전에 꼭 알아야 할 3가지

목업 화면과 실제 데이터가 다른 지점입니다.

**1. 효과 크기 단위는 `%p`가 아니라 `명/천명`이고, 유의하지 않습니다.**

목업은 `+2.3%p, p<0.05`로 되어 있지만 실제는 `+0.9496명/천명, p=0.4631`입니다.
`/api/analysis/did`의 `significance.is_significant`가 `false`이니 이 값으로 표기를 결정하세요.
"효과 있음"으로 표시하면 안 됩니다. 바로 쓸 수 있는 문장이 `significance.statement_ko`에 있습니다.

**2. 인과분석 그룹 구성은 6개 대 5개입니다.**

목업은 3개 대 3개였지만 실제는 처치군 6개(제천·보은·옥천·영동·괴산·단양), 비교군 5개(청주·충주·증평·진천·음성)입니다.
`/api/panel/group-timeseries` 응답의 `treatment_regions` / `control_regions`를 그대로 쓰세요.

**3. 2025년 데이터는 없습니다.**

패널은 2024년 12월까지입니다. 2025년을 요청하면 `data_status: "unavailable"`이 오고 값은 `null`입니다.
없는 값을 0으로 표시하지 말고 "데이터 없음"으로 표시해 주세요.

---

## 표시할 때 주의할 값

- **집행률이 `null`인 시군이 있습니다.** 청주·충주·증평·진천·음성은 기금 배분 대상이 아니라
  배분액이 0이고 집행률이 정의되지 않습니다. **0%가 아니라 "-" 또는 "해당 없음"으로** 표시하세요.
- **집행률은 성과 지표가 아닙니다.** 투입 진행률입니다. 성과는 청년 순이동률로 표시합니다.
- 집행률은 `execution_rate`(0~1)와 `execution_rate_pct`(%) 둘 다 옵니다. 화면에는 `_pct`를 쓰세요.
- 청년 순이동률이 **음수면 청년이 빠져나가고 있다**는 뜻입니다.
- `meta.notes`에 그 수치를 어떻게 계산했는지가 들어 있습니다. 툴팁에 쓰기 좋습니다.

---

## 로컬에서 띄우고 싶다면

```bash
uv venv --python 3.11
uv pip install -e ".[dev]"
cp .env.example .env
uv run python scripts/build_artifacts.py     # 최초 1회
uv run uvicorn app.main:app --reload --port 8000
```

http://localhost:8000/docs 로 확인합니다. 종료는 `pkill -f "uvicorn app.main"`.

Docker로 띄우려면 `docker compose up --build`.

---

## 막히면

- 응답 형태가 궁금하면 [/docs](https://2026-summer-semester-project-production.up.railway.app/docs)에서
  **Try it out**을 눌러보세요. 모든 엔드포인트에 실제 값 예시가 들어 있습니다.
- 500이나 502가 뜨면 백엔드 담당자에게 알려주세요. 요청 경로와 시각만 알려주면 로그로 확인됩니다.
- 필요한 데이터가 없거나 응답 형태를 바꾸는 게 나을 것 같으면 말씀해 주세요.

백엔드 내부 설계(데이터 규칙, 분석 아티팩트, 배포, 테스트)는 [docs/backend.md](docs/backend.md)에 있습니다.
