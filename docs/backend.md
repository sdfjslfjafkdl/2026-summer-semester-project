# 백엔드 문서

이 문서는 **백엔드·데이터 담당자용**이다. 프론트 연동에 필요한 내용은 [README.md](../README.md)에 있다.

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

---

## 6. 데이터 규칙 (수치가 이상해 보일 때 먼저 확인)

- **기금 금액은 지역-연도 중복 제거 후 합산.** 패널이 연도값을 12개월에 반복 결합해 두어 월별 합산 시 정확히 12배. 집계는 `Panel.fund_year_frame()`만 사용
- **1인당 기금 지표는 연말(12월) 인구를 분모로 재계산한 파생값.** 원본 컬럼은 분모가 월별 인구라 지역-연도 안에서도 값이 변동
- **비교군 5개 시군은 배분액이 0이라 집행률이 정의되지 않음(`null`).** 0%가 아님
- **`employment_insured_yoy_pct`의 2017년 132행은 구조적 결측.** 보간하지 않으며, 보간된 CSV는 적재 단계에서 거부
- **집행률은 성과 지표가 아닌 투입 진행률.** 성과는 `youth_net_migration_rate_per_1000`으로 측정
- **그룹 평균은 인구 가중이 아닌 지역 단순평균.** `meta.notes`에 매번 명시

---

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

---

## 11. 차년도 제안

- `/api/proposal?year=2026`은 규칙 기반
- 규칙 전문은 `app/services/proposal.py` 상단 주석에 수록되며 응답의 `basis.rules`로도 반환
- `basis.is_causal_estimate`는 항상 `false`. 1차 DID가 유의하지 않으므로 기술통계·진단 지표에 근거한 참고안임을 응답에서 명시
- 순위는 기금 배분 대상 6개 시군 안에서만 산정하고, 비배분 5개 시군은 진단만 제공

---

---

## 12. 투자계획서 작성 지원

완성본을 만드는 도구가 아니다. **데이터로 채울 수 있는 곳만 채우고, 사람이 결정해야 하는 곳은
구획과 작성 지침으로 남겨 넘긴다.** 서식은 한국지방재정공제회 '2026년 지방소멸대응기금
투자계획서 작성 안내서'(2025.1)를 따르며, 서식에 없는 항목은 만들지 않는다.

### 채움 모드

레지스트리는 [app/data/plan_sections.py](app/data/plan_sections.py)에 있고 27개 항목을 담는다.

| 모드 | 뜻 | 해당 항목 |
|---|---|---|
| `auto` | 패널·아티팩트로 서버가 채운다 | Ⅰ-1 인구현황·인구변동 추이, Ⅵ-2-① 연도별 소계 |
| `assisted` | 사람이 값을 주면 서식 톤 문장으로 만든다 | Ⅰ-2, Ⅲ-1, Ⅲ-3, Ⅲ-4-①, Ⅲ-별첨 |
| `manual` | 서버가 채우지 않고 빈 구획과 지침만 넣는다 | Ⅱ 전체, Ⅲ-2, Ⅲ-4-⑤, Ⅲ-5, Ⅳ, Ⅴ, Ⅵ-1 등 |

### 흐름

```bash
# 1. 초안 생성 — Layer 1 엔드포인트를 호출해 auto 섹션을 채운다
curl -X POST localhost:8000/api/plan/draft -H 'content-type: application/json' \
  -d '{"region": "제천시", "year": 2026}'

# 2. 사람이 섹션을 채운다 (manual 은 그대로 저장, assisted 는 문장으로 만든다)
curl -X POST localhost:8000/api/plan/plan_제천시_2026_01/sections/3-2 \
  -H 'content-type: application/json' -d '{"content": "부지는 신월동 시유지, 민원 없음"}'

# 3. 자연어로 고친다 (대상을 못 찾으면 되묻는다)
curl -X POST localhost:8000/api/plan/plan_제천시_2026_01/revise \
  -H 'content-type: application/json' -d '{"instruction": "Ⅲ-3 목표를 보수적으로"}'

# 4. 내보낸다
curl -X POST localhost:8000/api/plan/plan_제천시_2026_01/export \
  -H 'content-type: application/json' -d '{"format": "docx"}' -o 계획서_초안.docx
```

### 지켜지는 것

- **수치 가드가 문서에도 적용된다.** 계획서에 등장한 숫자는 `called_endpoints` 결과에 실재해야
  하고, 없는 숫자가 든 문장은 버려진다. 담당자가 직접 넣은 값은 예외로 허용하되
  `data_points` 의 `source_endpoint` 가 `human_input` 으로 표시된다
- **인과효과를 단정하지 않는다.** 모든 응답의 `meta.notes` 에 그 사실이 실린다
- **Ⅵ-2 는 사업 단위로 분해하지 않는다.** 패널이 지역-연도 단위라 연도별 소계만 자동으로 채우고
  사업별 행은 담당자 몫으로 남긴다. `values` 에 사업별 합계를 넣으면(예: `{"2022_배분액": 4800}`)
  자동 집계 소계와 대조해 어긋나면 경고를 낸다
- **Ⅲ-3 사업목표**는 안내서가 단순 실적지표(예산 집행률)를 금지하므로 청년 순이동률을 지표 후보로
  제시하고, 측정방법 문장과 연차별 목표값 후보를 패널에서 도출한다. 목표값 산출 규칙은
  `plan_builder.goal_targets` 주석에 있다
- **LLM 이 꺼져 있어도** auto 채움과 manual 구획 생성은 그대로 동작하고 assisted 만 템플릿 문장이 된다

### 내보내기

- docx 는 안내서의 목차(Ⅰ~Ⅵ)와 형식 규정(본문 휴먼명조 15pt, 참고사항 중고딕 13pt,
  여백 15/15/20/20mm, 머리말·꼬리말 10mm, 쪽번호)을 반영한다
- manual 구획은 회색 음영과 `[담당자 작성 필요]` 표시, 안내서의 【작성내용】과
  【기술 방향과 평가의 주안점】이 함께 들어간다
- 휴먼명조·중고딕은 한글(HWP) 글꼴이라 서버에 없는 경우가 많다. 없으면 대체 글꼴을 쓰고
  그 사실을 로그와 `X-Plan-Notes` 응답 헤더에 남긴다
- 문서 첫 장에 **초안이며 실제 제출은 hwp 서식으로 변환해야 한다**는 안내가 들어간다
- 작성 중인 계획서는 `PLAN_DIR`(컨테이너 기본값 `data/runtime/plans`)에 저장된다.
  볼륨이 없으면 메모리에만 있으므로 재시작 시 사라지고, 그 사실을 `meta.notes` 로 알린다

---

---

## 13. 테스트

- 네트워크 없이 결정적으로 동작. `conftest.py`에서 테스트 세션의 LLM을 강제 비활성화
- `.env`에 `LLM_ENABLED=true`가 있어도 실제 API 호출 없음
- 161개 통과. 사업내역서 PDF가 있으면 PDF 전제 테스트 3개가 추가되어 164개

---

---

## 14. 배포

컨테이너 이미지 하나로 배포한다. 분석 아티팩트는 **빌드 시점에 구워** 넣으므로 런타임에
계산이 끼지 않고, 컨테이너마다 다른 산출물이 나올 여지가 없다.

### 14.1 로컬에서 이미지 빌드·실행

```bash
docker build -t chungbuk-api .
docker run --rm -p 8000:8000 \
  -e CORS_ORIGINS="https://impact-advisor-ai.lovable.app,http://localhost:5173" \
  chungbuk-api

curl -s localhost:8000/api/health | python3 -m json.tool   # panel_rows: 1056
```

LLM까지 켜서 확인하려면 키를 **런타임 환경변수로만** 넘긴다 (이미지에 굽지 않는다):

```bash
docker run --rm -p 8000:8000 \
  -e LLM_ENABLED=true -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  chungbuk-api
```

### 14.2 로컬 개발 (소스 리로드)

```bash
docker compose up --build      # .env 를 읽고 app/ 을 바인드 마운트해 --reload 로 실행
```

### 14.3 환경변수 전체 목록

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PORT` | `8000` | 서버 포트. **Railway가 자동 주입**하므로 배포 시 직접 설정하지 않는다 |
| `APP_ENV` | `local` | 이미지에서는 `production` |
| `LOG_LEVEL` | `INFO` | |
| `CORS_ORIGINS` | lovable 도메인 | 콤마 구분. 프론트 도메인을 여기에 넣는다 |
| `LLM_ENABLED` | `false` | `false`면 규칙 기반 라우터·서술로 동작 |
| `ANTHROPIC_API_KEY` | (없음) | **런타임 환경변수로만.** 비어 있으면 `LLM_ENABLED=true`여도 규칙 기반으로 폴백 |
| `ANTHROPIC_MODEL` | `claude-opus-5` | |
| `LLM_TIMEOUT_SECONDS` | `60` | 서술 호출이 9~13초라 20초는 부족하다 |
| `INDEX_DIR` | `data/index` | 근거 검색 캐시. 이미지에서는 `/app/data/runtime/index` |
| `ARTIFACT_DIR` | `data/artifacts` | 분석 아티팩트. 이미지에 포함되어 있다 |
| `PLAN_DIR` | `data/runtime/plans` | 작성 중인 투자계획서. 볼륨이 없으면 메모리에만 남는다 |
| `DATA_DIR`, `PANEL_CSV`, `OOT_REGION_CSV`, `PANEL_README_MD`, `EVIDENCE_REGISTER_MD`, `EVIDENCE_PDF_DIR` | `.env.example` 참고 | 원자료 경로. 기본값으로 두면 된다 |

### 14.4 Railway 배포 절차

1. **프로젝트 생성** — Railway 대시보드에서 *New Project → Deploy from GitHub repo* 로 이 저장소를 선택한다.
   `railway.json`이 있으므로 빌더는 자동으로 Dockerfile을 쓴다.
2. **볼륨 추가** — 서비스의 *Variables → Volumes*에서 마운트 경로를 **`/app/data/runtime`** 으로 지정한다.
   근거 검색 캐시가 여기에 쌓인다. 볼륨이 비어 있어도 서버는 정상 기동하며, 첫 검색 요청이 캐시를 만든다.
   볼륨을 붙이지 않아도 동작한다 — 재기동할 때마다 캐시를 다시 만들 뿐이다.
3. **시작 커맨드는 비워 둔다** — 이미지의 `CMD`(`python -m app.server`)가 실행된다.
   *Settings → Deploy → Custom Start Command* 에 값이 들어 있으면 지운다.
   여기에 `uvicorn ... --port ${PORT:-8000}` 같은 걸 넣으면 Railway가 쉘 없이 실행해서
   `${PORT:-8000}`이 문자열 그대로 넘어가 `is not a valid integer`로 죽는다.
   꼭 직접 지정해야 한다면 쉘 확장이 없는 `python -m app.server` 를 쓴다.
4. **환경변수 설정** — *Variables* 탭에서 최소한 다음을 넣는다. `PORT`는 넣지 않는다(자동 주입).
   ```
   CORS_ORIGINS=https://impact-advisor-ai.lovable.app
   LLM_ENABLED=true
   ANTHROPIC_API_KEY=sk-ant-...
   LLM_TIMEOUT_SECONDS=60
   ```
   키를 넣지 않으면 규칙 기반으로만 동작한다. 데모는 그대로 돌아간다.
5. **배포 확인** — 헬스체크 경로는 `railway.json`에 `/api/health`로 설정되어 있다.
   배포 로그에서 `패널 적재 완료: 1056행` 을 확인하고, 공개 도메인에서
   `GET /api/health`가 `panel_rows: 1056`을 반환하는지 본다.
6. **도메인 발급** — *Settings → Networking → Generate Domain* 으로 공개 URL을 만든다.
7. **프론트 연결** — 프론트에서 이 URL을 API 베이스로 지정하고, 아래처럼 프론트 도메인을 CORS에 추가한다.

### 14.5 배포 후 프론트 도메인 추가

CORS는 코드가 아니라 환경변수로 관리한다. 프론트 도메인이 늘어나면 Railway *Variables* 에서
`CORS_ORIGINS` 값에 콤마로 이어 붙이고 재배포하면 된다.

```
CORS_ORIGINS=https://impact-advisor-ai.lovable.app,https://preview--impact-advisor-ai.lovable.app,http://localhost:5173
```

- 스킴(`https://`)까지 정확히 적는다. 경로나 끝 슬래시는 넣지 않는다
- 미리보기·스테이징 도메인이 따로 있으면 각각 추가한다
- 목록에 없는 오리진의 프리플라이트 요청은 400으로 거부된다 (의도된 동작)

### 14.6 이미지에 대해 알아둘 점

- **비root(`appuser`, uid 10001)로 실행**한다. 볼륨 소유자가 root라 캐시를 못 써도 검색은
  200으로 동작한다 — 캐시는 원본에서 다시 만들 수 있는 부가물이라 요청을 실패시키지 않는다
- **사업내역서 PDF는 저장소에 없으므로 이미지에도 없다.** 근거 검색은 등록부 3건 기준으로 동작한다.
  PDF를 포함하려면 빌드 전에 `data/raw/evidence/pdf/`에 넣는다
- `.dockerignore`가 `tests`, `evals`, `.git`, `.venv`, `data/index`를 제외한다

---

---

## 15. 프로젝트 구조

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
  raw/plan_template/   투자계획서 서식 안내서 PDF (git 제외, 팀 내부 공유)
  artifacts/           분석 결과 v1 아티팩트 (빌드 시 생성)
  index/               근거 검색 캐시 — 로컬 (git 제외)
  runtime/index/       근거 검색 캐시 — 컨테이너, Railway 볼륨 마운트 지점
  runtime/plans/       작성 중인 투자계획서
evals/
  run_eval.py          표준 질의 평가 러너
scripts/build_artifacts.py
tests/
Dockerfile             멀티스테이지 (빌드: uv + 아티팩트 생성 / 런타임: slim, 비root)
docker-compose.yml     로컬 개발용 (.env + 소스 바인드 마운트 + --reload)
railway.json           빌더·시작 커맨드·헬스체크(/api/health)
.dockerignore
```
