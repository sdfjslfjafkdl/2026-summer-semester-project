"""투자계획서 초안 생성과 섹션 채움 (Layer 1 + Layer 2).

설계 원칙
  - 완성본을 만들지 않는다. 데이터로 채울 수 있는 곳만 채우고 나머지는 구획으로 남긴다.
  - 계획서에 등장하는 모든 숫자는 호출한 Layer 1 결과나 사람이 직접 넣은 값에 실재해야 한다.
    chat.py 의 수치 가드(allowed_numbers, verify_numbers)를 그대로 쓴다.
  - 인과효과를 단정하지 않는다. 1차 DID 는 유의하지 않고 제안은 참고안이다.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.data.panel import FUND_YEARS, get_panel
from app.data.plan_sections import SECTIONS, PlanSection, get_section
from app.errors import ApiError
from app.routers import evidence as evidence_router
from app.routers import funds as funds_router
from app.routers import panel as panel_router
from app.routers import proposal as proposal_router
from app.services import plan_store
from app.services.chat import NUMBER_PATTERN, ToolCall, allowed_numbers, verify_numbers
from app.services.plan_store import StoredPlan, StoredSection, now_iso

logger = logging.getLogger(__name__)

DEFAULT_FUND = "local-extinction"
OUTCOME_METRIC = "youth_net_migration_rate_per_1000"
OUTCOME_LABEL = "청년 순이동률"
OUTCOME_UNIT = "명/천명"

NOT_CAUSAL_NOTE = (
    "이 문서의 수치는 기술통계와 진단 지표이며 확정된 인과효과가 아니다. "
    "1차 이중차분 추정이 통계적으로 유의하지 않아 기금 투입이 청년 순이동률을 개선했다고 단정하지 않는다."
)

GUARD_POLICY = (
    "계획서의 모든 숫자는 호출한 Layer 1 엔드포인트 결과 또는 담당자가 직접 입력한 값에 "
    "실재해야 한다. 그 밖의 숫자가 들어간 문장은 버린다."
)


# ── 도구 호출 ────────────────────────────────────────────────────


def _call(endpoint: str, params: dict, envelope) -> ToolCall:  # noqa: ANN001
    payload = envelope.model_dump()
    return ToolCall(endpoint=endpoint, params=params, data=payload["data"], meta=payload["meta"])


def collect_layer1(region: str, year: int) -> list[ToolCall]:
    """초안에 필요한 Layer 1 결과를 모은다. 새 계산을 만들지 않고 기존 엔드포인트만 쓴다."""
    panel = get_panel()
    calls: list[ToolCall] = []

    for fund_year in FUND_YEARS:
        calls.append(
            _call(
                f"/api/funds/{DEFAULT_FUND}/regions",
                {"fund_id": DEFAULT_FUND, "year": fund_year},
                funds_router.fund_regions(fund_id=DEFAULT_FUND, year=fund_year),
            )
        )
    calls.append(
        _call(
            f"/api/funds/{DEFAULT_FUND}/trend",
            {"fund_id": DEFAULT_FUND},
            funds_router.fund_trend(fund_id=DEFAULT_FUND),
        )
    )
    calls.append(
        _call(
            "/api/panel/timeseries",
            {"regions": region, "metric": OUTCOME_METRIC, "freq": "year"},
            panel_router.timeseries(
                regions=region, metric=OUTCOME_METRIC, from_="2017-01", to=panel.period_end, freq="year"
            ),
        )
    )
    for metric in ("youth_population_20_39", "population_total", "aged_population_ratio_pct"):
        calls.append(
            _call(
                "/api/panel/timeseries",
                {"regions": region, "metric": metric, "freq": "year"},
                panel_router.timeseries(
                    regions=region, metric=metric, from_="2017-01", to=panel.period_end, freq="year"
                ),
            )
        )
    calls.append(
        _call(
            "/api/proposal",
            {"year": year},
            proposal_router.proposal(year=year, include_evidence=True),
        )
    )
    calls.append(_call("/api/evidence/projects", {}, evidence_router.projects()))
    return calls


def _series(calls: list[ToolCall], metric: str, region: str) -> list[dict]:
    for call in calls:
        if call.endpoint != "/api/panel/timeseries":
            continue
        if call.data["metric"]["key"] != metric:
            continue
        for series in call.data["series"]:
            if series["region"] == region:
                return series["points"]
    return []


def _fund_row(calls: list[ToolCall], year: int, region: str) -> dict | None:
    for call in calls:
        if not call.endpoint.endswith("/regions") or call.params.get("year") != year:
            continue
        for row in call.data["regions"]:
            if row["region"] == region:
                return row
    return None


def _proposal_item(calls: list[ToolCall], region: str) -> dict | None:
    for call in calls:
        if call.endpoint == "/api/proposal":
            for item in call.data["proposals"]:
                if item["region"] == region:
                    return item
    return None


def _region_projects(calls: list[ToolCall], region: str) -> list[dict]:
    for call in calls:
        if call.endpoint == "/api/evidence/projects":
            return [p for p in call.data["projects"] if p["region"] == region]
    return []


# ── 목표값 산출 (Layer 1 결정적 계산) ─────────────────────────────


def goal_targets(calls: list[ToolCall], region: str) -> ToolCall:
    """Ⅲ-3 연차별 목표값 후보.

    안내서는 단순 실적지표(예: 예산 집행률)가 아니라 사업의 성과에 해당하는 목표를 고르라고 한다.
    그래서 이 서비스의 주 결과변수인 청년 순이동률을 지표로 제시한다.

    목표값은 패널에서만 끌어온다. 규칙은 이렇다.
      최근 3년(2022~2024) 연평균 개선폭 = (2024년 값 − 2022년 값) ÷ 2
      개선 추세면  : 그 개선폭을 그대로 이어간 값을 1·2·3차년 목표로 둔다.
      악화 추세면  : 추세를 그대로 미는 것은 목표가 될 수 없으므로,
                    최근 3년 평균 수준에서 악화를 멈추는 것을 1차년 목표로 두고
                    이후는 최근 3년 중 가장 좋았던 값까지 두 단계로 회복하는 값을 둔다.

    산출값은 새로 만든 숫자이므로 도구 결과로 등록해 출처를 남긴다. 그래야 수치 가드를 통과한다.
    """
    points = {p["period"]: p["value"] for p in _series(calls, OUTCOME_METRIC, region)}
    recent = {str(y): points.get(str(y)) for y in FUND_YEARS}
    values = [v for v in recent.values() if v is not None]
    if not values:
        raise ApiError(
            status_code=422,
            code="insufficient_panel_data",
            message=f"{region}의 최근 3년 청년 순이동률을 찾지 못해 목표값을 만들 수 없습니다.",
        )

    first, last = recent[str(FUND_YEARS[0])], recent[str(FUND_YEARS[-1])]
    mean_recent = sum(values) / len(values)
    best_recent = max(values)
    annual_change = (last - first) / (len(FUND_YEARS) - 1) if first is not None and last is not None else 0.0

    if annual_change > 0:
        basis = "최근 3년 연평균 개선폭을 이어가는 값"
        targets = [round(last + annual_change * n, 2) for n in (1, 2, 3)]
    else:
        basis = "악화 중단 후 최근 3년 최고 수준으로 회복하는 값"
        step = (best_recent - mean_recent) / 2 if best_recent > mean_recent else 0.0
        targets = [round(mean_recent + step * n, 2) for n in (0, 1, 2)]

    return ToolCall(
        endpoint="internal:plan_goal_targets",
        params={"region": region, "metric": OUTCOME_METRIC, "years": list(FUND_YEARS)},
        data={
            "metric": OUTCOME_METRIC,
            "metric_label": OUTCOME_LABEL,
            "unit": OUTCOME_UNIT,
            "recent_values": recent,
            "recent_mean": round(mean_recent, 2),
            "recent_best": round(best_recent, 2),
            "annual_change": round(annual_change, 2),
            "target_basis": basis,
            "year1_target": targets[0],
            "year2_target": targets[1],
            "year3_target": targets[2],
            "measurement": (
                "행정안전부 주민등록 인구통계와 국가통계포털 국내인구이동 자료로 "
                "20–39세 순이동자 합계를 20–39세 주민등록인구로 나눈 뒤 1,000을 곱해 산출하고, "
                "연도별로 12개월 평균을 낸다."
            ),
        },
        meta={
            "source": "chungbuk_monthly_model_panel_2017_2024.csv",
            "data_status": "derived",
            "notes": [basis, GUARD_POLICY],
        },
    )


# ── 수치 가드 ───────────────────────────────────────────────────


def scrub(text: str, allowed: set[float]) -> tuple[str, list[str]]:
    """도구 결과에 없는 숫자가 든 문장을 버린다.

    문장 단위로 지우는 이유는, 숫자만 도려내면 뜻이 바뀐 문장이 남기 때문이다.
    """
    kept: list[str] = []
    rejected: list[str] = []
    for block in text.split("\n"):
        if not block.strip():
            kept.append(block)
            continue
        sentences = re.split(r"(?<=다\.)\s+|(?<=\.)\s+", block)
        good = []
        for sentence in sentences:
            offending = verify_numbers(sentence, allowed)
            if offending:
                rejected.extend(offending)
            else:
                good.append(sentence)
        if good:
            kept.append(" ".join(good))
    return "\n".join(kept).strip(), rejected


def numbers_in(text: str) -> list[float]:
    found = []
    for token in NUMBER_PATTERN.findall(text):
        try:
            found.append(float(token.replace(",", "")))
        except ValueError:
            continue
    return found


# ── auto 섹션 ──────────────────────────────────────────────────


def _fmt(value: float | None, digits: int = 2) -> str:
    return "값 없음" if value is None else f"{value:,.{digits}f}"


def fill_1_1(calls: list[ToolCall], region: str) -> tuple[str, list[dict]]:
    """Ⅰ-1 인구현황과 청년 인구이동 추이."""
    population = _series(calls, "population_total", region)
    youth = _series(calls, "youth_population_20_39", region)
    aged = _series(calls, "aged_population_ratio_pct", region)
    net = _series(calls, OUTCOME_METRIC, region)
    if not population or not net:
        return "", []

    latest_year = population[-1]["period"]
    lines = [
        f"○ 인구현황 ({latest_year}년 연평균)",
        f"  - 주민등록 총인구 {_fmt(population[-1]['value'], 0)}명",
        f"  - 20–39세 청년인구 {_fmt(youth[-1]['value'], 0)}명",
        f"  - 고령인구비율 {_fmt(aged[-1]['value'], 1)}%",
        "",
        f"○ 청년 순이동률 추이 ({OUTCOME_UNIT}, 연평균)",
    ]
    data_points = [
        {"label": f"{latest_year}년 총인구(연평균)", "value": population[-1]["value"], "unit": "명",
         "source_endpoint": "/api/panel/timeseries"},
        {"label": f"{latest_year}년 청년인구(연평균)", "value": youth[-1]["value"], "unit": "명",
         "source_endpoint": "/api/panel/timeseries"},
        {"label": f"{latest_year}년 고령인구비율(연평균)", "value": aged[-1]["value"], "unit": "%",
         "source_endpoint": "/api/panel/timeseries"},
    ]
    for point in net:
        lines.append(f"  - {point['period']}년 {_fmt(point['value'])}")
        data_points.append(
            {
                "label": f"{point['period']}년 청년 순이동률",
                "value": point["value"],
                "unit": OUTCOME_UNIT,
                "source_endpoint": "/api/panel/timeseries",
            }
        )

    first, last = net[0], net[-1]
    lines += [
        "",
        f"○ {first['period']}년 {_fmt(first['value'])}에서 {last['period']}년 {_fmt(last['value'])}로 "
        f"변화했다. 음수는 20–39세 인구가 순유출되고 있음을 뜻한다.",
    ]
    return "\n".join(lines), data_points


def fill_6_2_1(calls: list[ToolCall], region: str) -> tuple[str, list[dict], list[str]]:
    """Ⅵ-2-① 연도별 소계. 사업별 행은 담당자 몫으로 남긴다."""
    lines = ["○ 연도별 기금사업 추진 성과표 (단위: 백만원)", ""]
    data_points: list[dict] = []
    warnings: list[str] = []

    for year in FUND_YEARS:
        row = _fund_row(calls, year, region)
        if row is None:
            continue
        rate = row["execution_rate_pct"]
        rate_text = "정의되지 않음(배분액 0)" if rate is None else f"{_fmt(rate, 1)}%"
        lines.append(
            f"  - {year}년 소계: 배분액 {_fmt(row['allocation_million_krw'], 0)}, "
            f"집행액 {_fmt(row['execution_million_krw'], 0)}, 집행률 {rate_text} "
            f"(사업 수 {_fmt(row['project_count'], 0)}건)"
        )
        for label, key, unit in (
            ("배분액", "allocation_million_krw", "백만원"),
            ("집행액", "execution_million_krw", "백만원"),
            ("집행률", "execution_rate_pct", "%"),
            ("사업 수", "project_count", "건"),
        ):
            data_points.append(
                {
                    "label": f"{year}년 {label}",
                    "value": row[key],
                    "unit": unit,
                    "source_endpoint": f"/api/funds/{DEFAULT_FUND}/regions",
                }
            )

    projects = _region_projects(calls, region)
    if projects:
        lines += ["", "○ 근거 등록부에 있는 사업 (사업별 행 작성 시 참고)"]
        for project in projects:
            lines.append(
                f"  - {project['project_name']}: 기금액 {_fmt(project['fund_million_krw'], 0)}백만원, "
                f"사업기간 {project['official_period']}, 근거등급 {project['grade']}"
            )
            data_points.append(
                {
                    "label": f"{project['project_name']} 기금액",
                    "value": project["fund_million_krw"],
                    "unit": "백만원",
                    "source_endpoint": "/api/evidence/projects",
                }
            )
        warnings.append(
            "등록부의 기금액은 사업 전체 기간 기준이라 연도별 배분액 소계와 단위가 다르다. "
            "사업별 행을 채울 때 연도별로 나누어 적어야 한다."
        )

    lines += [
        "",
        "※ 사업별 행(사업명·배분액·집행액·완료 여부)은 담당자가 작성한다. "
        "이 서비스의 패널은 지역-연도 단위라 사업 단위로 분해할 수 없다.",
    ]
    return "\n".join(lines), data_points, warnings


# ── assisted 섹션 ──────────────────────────────────────────────


def draft_3_3(calls: list[ToolCall], region: str) -> tuple[str, list[dict]]:
    """Ⅲ-3 사업목표 후보. 지표·측정방법·연차별 목표값을 데이터에서 뽑아 제시한다."""
    targets = next(c for c in calls if c.endpoint == "internal:plan_goal_targets")
    d = targets.data
    recent = d["recent_values"]

    lines = [
        "○ (정량목표) 사업목표 지표 후보",
        f"  - 지표: {d['metric_label']} ({d['unit']}, 지표키 {d['metric']})",
        "  - 선정 사유: 안내서는 단순 실적지표(예: 예산 집행률)가 아니라 사업의 성과에 해당하는 "
        "목표를 선정하도록 하고 있다. 집행률은 투입 진행률이므로 성과지표로 쓰지 않는다.",
        "",
        "○ 측정방법",
        f"  - {d['measurement']}",
        "",
        "○ 최근 실적",
    ]
    data_points = []
    for year, value in recent.items():
        lines.append(f"  - {year}년 {_fmt(value)}")
        data_points.append(
            {
                "label": f"{year}년 {d['metric_label']}",
                "value": value,
                "unit": d["unit"],
                "source_endpoint": "/api/panel/timeseries",
            }
        )
    lines += [
        f"  - 최근 3년 평균 {_fmt(d['recent_mean'])}, 최고 {_fmt(d['recent_best'])}, "
        f"연평균 변화 {_fmt(d['annual_change'])}",
        "",
        "○ 연차별 목표값 후보",
        f"  - 산출 근거: {d['target_basis']}",
        f"  - 1차년 {_fmt(d['year1_target'])}",
        f"  - 2차년 {_fmt(d['year2_target'])}",
        f"  - 3차년 {_fmt(d['year3_target'])}",
        "",
        "※ 목표값은 패널 데이터에서 도출한 후보다. 사업의 규모와 대상 범위를 고려해 담당자가 확정한다.",
    ]
    for label, key in (("1차년 목표", "year1_target"), ("2차년 목표", "year2_target"), ("3차년 목표", "year3_target")):
        data_points.append(
            {"label": label, "value": d[key], "unit": d["unit"], "source_endpoint": "internal:plan_goal_targets"}
        )
    return "\n".join(lines), data_points


ASSISTED_PROMPTS: dict[str, str] = {
    "1-2": "여건분석에서 드러난 문제와 그것이 투자계획의 방향·전략과 어떻게 이어지는지 입력하세요.",
    "3-1": "중점사업의 추진 배경과 목적, 사업의 주요 내용과 기대효과를 입력하세요.",
    "3-3": "위 목표값 후보를 확정하거나 조정할 값과 사유를 입력하세요.",
    "3-4-1": "그간 추진한 내용(신규사업이면 선제적 노력)을 시기와 함께 입력하세요.",
    "3-annex": "기금사업명과 체크리스트 각 항목의 여/부를 입력하세요.",
}


def assisted_template(section: PlanSection, region: str, calls: list[ToolCall]) -> tuple[str, list[dict]]:
    """LLM 없이도 나오는 기본 문장. 데이터로 뒷받침되는 부분만 넣는다."""
    if section.section_id == "3-3":
        return draft_3_3(calls, region)

    if section.section_id == "1-2":
        item = _proposal_item(calls, region)
        net = _series(calls, OUTCOME_METRIC, region)
        if not item or not net:
            return "", []
        drivers = {d["metric"]: d for d in item["drivers"]}
        recent_mean = drivers["youth_net_migration_rate_per_1000"]["value"]
        out_gap = drivers["youth_out_migration_rate_per_1000"]["value"]
        in_gap = drivers["youth_in_migration_rate_per_1000"]["value"]
        text = (
            f"○ {region}의 최근 3년 청년 순이동률은 평균 {_fmt(recent_mean)}{OUTCOME_UNIT}이다.\n"
            f"  - 전출률은 11개 시군 중앙값 대비 {_fmt(out_gap)}{OUTCOME_UNIT}, "
            f"전입률 부족분은 {_fmt(in_gap)}{OUTCOME_UNIT}이다.\n"
            f"  - 진단 결과 권장 사업 유형은 {item['recommended_project_type']}이며, "
            f"판단 근거는 다음과 같다. {item['recommended_type_reason']}\n"
            f"※ {NOT_CAUSAL_NOTE}"
        )
        points = [
            {"label": "최근 3년 청년 순이동률 평균", "value": recent_mean, "unit": OUTCOME_UNIT,
             "source_endpoint": "/api/proposal"},
            {"label": "전출률 중앙값 대비 차", "value": out_gap, "unit": OUTCOME_UNIT,
             "source_endpoint": "/api/proposal"},
            {"label": "전입률 중앙값 대비 부족분", "value": in_gap, "unit": OUTCOME_UNIT,
             "source_endpoint": "/api/proposal"},
        ]
        return text, points

    if section.section_id == "3-1":
        item = _proposal_item(calls, region)
        if not item:
            return "", []
        return (
            f"○ (배경) {item['rationale_ko']}\n"
            f"○ (목적) 권장 사업 유형은 {item['recommended_project_type']}이며 "
            f"배분 조정 방향은 {item['allocation_direction']}이다.\n"
            f"※ {NOT_CAUSAL_NOTE}"
        ), []

    if section.section_id == "3-4-1":
        projects = _region_projects(calls, region)
        if not projects:
            return "", []
        lines = ["○ 등록부에서 확인된 추진 근거"]
        points = []
        for project in projects:
            lines.append(
                f"  - {project['project_name']} (근거등급 {project['grade']}, "
                f"기금액 {_fmt(project['fund_million_krw'], 0)}백만원, 사업기간 {project['official_period']})"
            )
            lines.append(f"    · {project['evidence_note']}")
            points.append(
                {"label": f"{project['project_name']} 기금액", "value": project["fund_million_krw"],
                 "unit": "백만원", "source_endpoint": "/api/evidence/projects"}
            )
        lines.append("※ 등급 C 사업은 2025년 이후 착수라 2017~2024 성과 근거로 쓰지 않는다.")
        return "\n".join(lines), points

    if section.section_id == "3-annex":
        return (
            "○ 체크리스트 (기금사업별 작성)\n"
            "  1. 기금 목적에 현저히 위배되는 사업 포함 여부: (여/부)\n"
            "  2. 국고보조사업 지방비 매칭 부담액으로 기금 사용 여부: (여/부)\n"
            "  3. 인건비·경상비 등 소모성 경비 사용 여부: (여/부)\n"
            "  3-1. 현금성 지원사업 사용 여부: (여/부)\n"
            "  3-2. 외유성 경비 사용 여부: (여/부)\n"
            "  4. 거점 생활인프라와 직접 관련 없는 사업 여부: (여/부)\n"
            "  5. 부지매입비 포함 여부: (여/부)"
        ), []

    return "", []


# ── 초안 생성 ───────────────────────────────────────────────────


def _status_for(section: PlanSection, content: str) -> str:
    if not content.strip():
        return "placeholder" if section.fill_mode == "manual" else "awaiting_human"
    return "filled" if section.fill_mode == "auto" else "awaiting_human"


def build_draft(region: str, year: int) -> tuple[StoredPlan, list[str]]:
    panel = get_panel()
    panel.require_regions([region])
    last_year = max(panel.available_years)
    if year <= last_year:
        raise ApiError(
            status_code=422,
            code="invalid_plan_year",
            message=(
                f"{year}년은 이미 관측치가 있는 연도입니다. 투자계획서는 {last_year + 1}년 이후를 대상으로 합니다."
            ),
            field="year",
            allowed_values=[str(y) for y in range(last_year + 1, last_year + 6)],
        )

    calls = collect_layer1(region, year)
    calls.append(goal_targets(calls, region))
    allowed = allowed_numbers(calls)

    plan = StoredPlan(
        plan_id=plan_store.make_plan_id(region, year),
        region=region,
        year=year,
        called_endpoints=[c.endpoint for c in calls],
        tool_results=[c.to_dict() for c in calls],
    )

    notes: list[str] = []
    for section in SECTIONS:
        content, points, warnings = "", [], []
        if section.section_id == "1-1":
            content, points = fill_1_1(calls, region)
        elif section.section_id == "6-2-1":
            content, points, warnings = fill_6_2_1(calls, region)
        elif section.fill_mode == "assisted":
            content, points = assisted_template(section, region, calls)

        rejected: list[str] = []
        if content:
            content, rejected = scrub(content, allowed)
        if rejected:
            warnings.append(
                f"도구 결과에 없는 숫자가 있어 해당 문장을 제거했다: {', '.join(sorted(set(rejected)))}"
            )
            notes.append(f"{section.number} 에서 수치 검증에 걸린 문장을 제거했다.")

        source = "layer1" if content and section.fill_mode == "auto" else (
            "template" if content else "none"
        )
        plan.sections[section.section_id] = StoredSection(
            section_id=section.section_id,
            content=content or None,
            source=source,
            status=_status_for(section, content),
            data_points=points,
            warnings=warnings,
            updated_at=now_iso(),
        )

    plan_store.record_history(plan, "draft", [], "초안 생성")
    plan_store.save(plan)
    if not plan.persisted:
        notes.append(
            "계획서를 파일로 저장하지 못했다. 프로세스가 재시작되면 사라지므로 내보내기를 먼저 하는 것이 좋다."
        )
    return plan, notes


# ── 섹션 채우기 ─────────────────────────────────────────────────


AMOUNT_KEY = re.compile(r"^(?P<year>20\d{2})[_\s]*(?P<kind>배분액|집행액|allocation|execution)$")


def check_subtotal_consistency(plan: StoredPlan, values: dict[str, Any]) -> list[str]:
    """Ⅵ-2 사업별 합계와 자동 채운 연도별 소계를 대조한다.

    values 예: {"2022_배분액": 4800, "2022_집행액": 4464}
    """
    warnings: list[str] = []
    auto_points = {
        point["label"]: point["value"]
        for point in plan.sections["6-2-1"].data_points
    }
    for key, raw in (values or {}).items():
        match = AMOUNT_KEY.match(str(key).strip())
        if not match:
            continue
        try:
            entered = float(str(raw).replace(",", ""))
        except ValueError:
            continue
        year = match.group("year")
        kind = match.group("kind")
        label = f"{year}년 " + ("배분액" if kind in {"배분액", "allocation"} else "집행액")
        subtotal = auto_points.get(label)
        if subtotal is None:
            continue
        if abs(entered - float(subtotal)) > 0.5:
            warnings.append(
                f"{label} 불일치: 사업별 합계 {entered:,.0f}백만원, "
                f"자동 집계 소계 {float(subtotal):,.0f}백만원. "
                "사업별 행이 누락되었거나 연도 구분이 어긋났을 수 있다."
            )
    return warnings


def update_section(plan: StoredPlan, section_id: str, content: str, values: dict | None) -> tuple[StoredSection, list[str]]:
    section = get_section(section_id)
    stored = plan.sections[section_id]

    human_numbers = numbers_in(content)
    for raw in (values or {}).values():
        human_numbers.extend(numbers_in(str(raw)))
    plan.human_numbers.extend(human_numbers)

    warnings: list[str] = []
    rejected: list[str] = []

    if section.fill_mode == "manual":
        # 사람이 쓴 그대로 저장한다. 서버가 문장을 만들지 않으므로 수치 가드 대상이 아니다.
        new_content = content.strip()
        source = "human_input"
    else:
        from app.services import plan_llm

        base = plan_llm.compose_assisted(section, content, values, plan)
        allowed = allowed_numbers([ToolCall(**c) for c in plan.tool_results]) | set(plan.human_numbers)
        new_content, rejected = scrub(base, allowed)
        if rejected:
            warnings.append(
                "도구 결과에도 입력값에도 없는 숫자가 있어 해당 문장을 제거했다: "
                + ", ".join(sorted(set(rejected)))
            )
        source = "llm" if plan_llm.llm_used() else "template"

    if section_id in {"6-2-1", "6-2-2"}:
        warnings.extend(check_subtotal_consistency(plan, values or {}))

    points = list(stored.data_points)
    for key, raw in (values or {}).items():
        try:
            numeric = float(str(raw).replace(",", ""))
        except ValueError:
            continue
        points.append(
            {"label": str(key), "value": numeric, "unit": "", "source_endpoint": "human_input"}
        )
    # 본문에 직접 적은 숫자도 출처를 남긴다. 도구 결과에 없는 값이 허용된 이유가
    # "사람이 그렇게 적었기 때문"이라는 사실이 응답에서 보여야 한다.
    tool_allowed = allowed_numbers([ToolCall(**c) for c in plan.tool_results])
    for number in numbers_in(new_content or ""):
        if any(abs(number - candidate) < 1e-6 for candidate in tool_allowed):
            continue
        points.append(
            {
                "label": "담당자가 본문에 직접 적은 수치",
                "value": number,
                "unit": "",
                "source_endpoint": "human_input",
            }
        )

    stored.content = new_content or None
    stored.source = source
    stored.status = "filled" if new_content else stored.status
    stored.data_points = points
    stored.warnings = warnings
    stored.version += 1
    stored.updated_at = now_iso()

    plan.version += 1
    plan_store.record_history(plan, "section_update", [section_id], f"{section.number} 갱신")
    plan_store.save(plan)
    return stored, rejected


# ── 진행률 ──────────────────────────────────────────────────────


def progress(plan: StoredPlan) -> dict:
    total = len(SECTIONS)
    filled = sum(1 for s in plan.sections.values() if s.status == "filled")
    auto_filled = sum(
        1
        for section in SECTIONS
        if section.fill_mode == "auto" and plan.sections[section.section_id].status == "filled"
    )
    assisted_pending = sum(
        1
        for section in SECTIONS
        if section.fill_mode == "assisted" and plan.sections[section.section_id].status != "filled"
    )
    manual_pending = sum(
        1
        for section in SECTIONS
        if section.fill_mode == "manual" and plan.sections[section.section_id].status != "filled"
    )
    return {
        "total_sections": total,
        "auto_filled": auto_filled,
        "assisted_pending": assisted_pending,
        "manual_pending": manual_pending,
        "awaiting_human": assisted_pending + manual_pending,
        "filled": filled,
        "completion_pct": round(filled / total * 100, 2),
    }


def summarize(plan: StoredPlan) -> dict:
    """비전문가용 요약. 다섯 문장 이내, 숫자는 모두 도구 결과에서 인용한다."""
    calls = [ToolCall(**c) for c in plan.tool_results]
    allowed = allowed_numbers(calls) | set(plan.human_numbers)
    stats = progress(plan)
    missing = missing_required(plan)

    sentences: list[str] = [
        f"이 문서는 {plan.region}의 {plan.year}년 지방소멸대응기금 투자계획서 초안입니다."
    ]
    evidence: list[dict] = []

    item = _proposal_item(calls, plan.region)
    if item:
        drivers = {d["metric"]: d for d in item["drivers"]}
        recent = drivers[OUTCOME_METRIC]["value"]
        sentences.append(
            f"{plan.region}의 최근 3년 청년 순이동률은 평균 {_fmt(recent)}{OUTCOME_UNIT}이며, "
            "음수는 청년 인구가 순유출되고 있음을 뜻합니다."
        )
        evidence.append(
            {"label": "최근 3년 청년 순이동률 평균", "value": recent, "unit": OUTCOME_UNIT,
             "source_endpoint": "/api/proposal"}
        )

    row = _fund_row(calls, max(FUND_YEARS), plan.region)
    if row and row["execution_rate_pct"] is not None:
        sentences.append(
            f"{max(FUND_YEARS)}년 기금은 배분액 {_fmt(row['allocation_million_krw'], 0)}백만원 중 "
            f"{_fmt(row['execution_million_krw'], 0)}백만원이 집행되어 집행률은 "
            f"{_fmt(row['execution_rate_pct'], 2)}%입니다."
        )
        evidence.append(
            {"label": f"{max(FUND_YEARS)}년 집행률", "value": row["execution_rate_pct"], "unit": "%",
             "source_endpoint": f"/api/funds/{DEFAULT_FUND}/regions"}
        )
    elif row:
        sentences.append(
            f"{plan.region}은 {max(FUND_YEARS)}년 기금 배분 대상이 아니어서 집행률이 정의되지 않습니다."
        )

    if item:
        sentences.append(
            f"진단 결과 권장 사업 유형은 {item['recommended_project_type']}이고 배분 조정 방향은 "
            f"{item['allocation_direction']}이며, 이는 확정된 인과효과가 아니라 기술통계와 진단 지표에 "
            "근거한 참고안입니다."
        )

    sentences.append(
        f"서식의 {stats['total_sections']}개 항목 중 {stats['filled']}개가 채워졌고 "
        f"{stats['awaiting_human']}개는 담당자 작성이 필요합니다."
    )

    cleaned: list[str] = []
    rejected_all: list[str] = []
    for sentence in sentences[:5]:
        text, rejected = scrub(sentence, allowed)
        rejected_all.extend(rejected)
        if text:
            cleaned.append(text)

    notes: list[str] = []
    if rejected_all:
        notes.append(
            "근거 없는 숫자가 있어 일부 문장을 제외했다: " + ", ".join(sorted(set(rejected_all)))
        )
    if missing:
        notes.append(
            f"필수 항목 {len(missing)}개가 비어 있어 아직 제출할 수 없다: {', '.join(missing[:5])}"
            + (" 등" if len(missing) > 5 else "")
        )
    return {"sentences": cleaned, "evidence": evidence, "missing": missing, "notes": notes}


def missing_required(plan: StoredPlan) -> list[str]:
    return [
        section.number
        for section in SECTIONS
        if section.required and plan.sections[section.section_id].status != "filled"
    ]
