"""규칙 기반 라우터 (Layer 2 폴백).

LLM_ENABLED=false 이거나 LLM 호출이 실패해도 전체 파이프라인이 돌아가야 한다.
발표 당일 네트워크 문제로 데모가 죽지 않게 하려는 요구사항이라, 이 모듈만으로도
질문 → 의도 → 슬롯 추출이 끝나야 한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.data.metrics import METRICS, TIMESERIES_METRIC_KEYS
from app.data.panel import CONTROL_REGIONS, TREATED_REGIONS

# ── 의도 ────────────────────────────────────────────────────────
INTENT_FUND = "fund_execution"
INTENT_TIMESERIES = "metric_timeseries"
INTENT_COMPARISON = "region_comparison"
INTENT_CAUSAL = "causal_analysis"
INTENT_EVIDENCE = "evidence_search"
INTENT_PROPOSAL = "proposal"
INTENT_OUT_OF_SCOPE = "out_of_scope"

INTENTS = (
    INTENT_FUND,
    INTENT_TIMESERIES,
    INTENT_COMPARISON,
    INTENT_CAUSAL,
    INTENT_EVIDENCE,
    INTENT_PROPOSAL,
    INTENT_OUT_OF_SCOPE,
)

INTENT_LABELS_KO = {
    INTENT_FUND: "기금 집행 현황 조회",
    INTENT_TIMESERIES: "지표 시계열 조회",
    INTENT_COMPARISON: "지역 간 비교",
    INTENT_CAUSAL: "인과분석 결과 조회",
    INTENT_EVIDENCE: "사업 근거 검색",
    INTENT_PROPOSAL: "차년도 제안 조회",
    INTENT_OUT_OF_SCOPE: "범위 밖 질문",
}

# 가중치가 큰 표현이 작은 표현을 이긴다.
# 예) "집행률과 인구 유출의 관계" 는 '집행률'(기금)보다 '관계'(인과)가 강하게 걸린다.
INTENT_KEYWORDS: dict[str, dict[str, float]] = {
    INTENT_CAUSAL: {
        "인과": 5.0, "효과": 3.0, "영향": 4.0, "관계": 4.5, "상관": 4.0,
        "did": 5.0, "이중차분": 5.0, "유의": 4.0, "통계적": 3.0, "검증": 2.5,
        "때문": 2.0, "덕분": 2.0, "효과가": 3.0,
    },
    INTENT_FUND: {
        "집행률": 3.0, "집행": 2.5, "배분액": 3.0, "배분": 2.0, "배정": 2.5,
        "예산": 2.0, "기금": 1.5, "사업비": 2.0, "미집행": 3.0, "얼마": 1.5,
        "총액": 2.0, "투입": 1.5,
    },
    INTENT_TIMESERIES: {
        "추이": 3.0, "시계열": 3.0, "변화": 2.0, "추세": 2.5, "순이동": 2.5,
        "유출": 2.0, "유입": 2.0, "인구": 1.5, "청년": 1.0, "고령": 2.0,
        "고용": 2.0, "몇 명": 1.5, "그래프": 2.0,
    },
    INTENT_COMPARISON: {
        "비교": 3.5, "대비": 2.0, "차이": 2.5, "vs": 3.0, "어디가": 3.0,
        "가장": 2.0, "제일": 2.0, "순위": 2.5, "많은": 1.5, "높은": 1.5, "낮은": 1.5,
    },
    INTENT_EVIDENCE: {
        "근거": 3.5, "사업내역서": 4.0, "문서": 3.0, "자료": 2.0, "등급": 3.0,
        "어떤 사업": 3.0, "사업 목록": 3.0, "출처": 3.0, "원문": 3.0, "실명제": 3.0,
    },
    INTENT_PROPOSAL: {
        "제안": 3.5, "권장": 3.0, "추천": 3.0, "내년": 3.0, "차년도": 3.5,
        "투자계획": 3.5, "우선순위": 3.0, "어디에 투자": 3.5, "2026": 2.5, "2027": 2.5,
        "해야": 1.5, "필요한": 1.0,
    },
}

# 데이터 범위 밖 신호
OUT_OF_SCOPE_REGIONS = (
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충남", "충청남", "전북", "전남", "경북", "경남", "제주",
)
OUT_OF_SCOPE_TOPICS = ("날씨", "주식", "환율", "코스피", "레시피", "번역", "축구", "영화")

SCOPE_STATEMENT = (
    "이 서비스는 충북 11개 시군, 2017-01~2024-12(96개월), 지방소멸대응기금 1종만 다룹니다."
)


def _region_aliases() -> dict[str, str]:
    """'제천', '제천시', '제천 시' 를 모두 같은 지역으로 매칭한다."""
    aliases: dict[str, str] = {}
    for region in (*TREATED_REGIONS, *CONTROL_REGIONS):
        stem = region[:-1]  # 시/군 접미 제거
        suffix = region[-1]
        for form in (region, stem, f"{stem} {suffix}"):
            aliases[form] = region
    return aliases


REGION_ALIASES = _region_aliases()

# 처치군 전체를 가리키는 표현
TREATED_GROUP_ALIASES = ("소멸위험", "인구감소지역", "처치군", "인구감소 지역", "대상 시군")
CONTROL_GROUP_ALIASES = ("비교군", "비처치", "대조군")

METRIC_ALIASES: dict[str, str] = {}
for metric in METRICS:
    METRIC_ALIASES[metric.label_ko] = metric.key
    for alias in metric.aliases:
        METRIC_ALIASES[alias] = metric.key


@dataclass
class Route:
    intent: str
    intent_label_ko: str
    regions: list[str] = field(default_factory=list)
    region_group: str | None = None  # treatment | control | None
    year: int | None = None
    metric: str | None = None
    fund_id: str | None = None
    confidence: float = 0.0
    router: str = "rules"  # rules | llm
    matched_keywords: list[str] = field(default_factory=list)
    out_of_scope_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "intent_label_ko": self.intent_label_ko,
            "regions": self.regions,
            "region_group": self.region_group,
            "year": self.year,
            "metric": self.metric,
            "fund_id": self.fund_id,
            "confidence": round(self.confidence, 3),
            "router": self.router,
            "matched_keywords": self.matched_keywords,
            "out_of_scope_reason": self.out_of_scope_reason,
        }


def extract_regions(question: str) -> tuple[list[str], str | None]:
    text = question.lower()
    found: list[str] = []
    for alias, region in REGION_ALIASES.items():
        if alias in question and region not in found:
            found.append(region)

    group: str | None = None
    if any(alias in question for alias in TREATED_GROUP_ALIASES):
        group = "treatment"
    elif any(alias in question for alias in CONTROL_GROUP_ALIASES):
        group = "control"
    elif "충북" in question or "충청북도" in text:
        group = "all"
    return found, group


def extract_year(question: str) -> int | None:
    years = [int(y) for y in re.findall(r"(20\d{2})\s*년?", question)]
    return years[-1] if years else None


def extract_metric(question: str) -> str | None:
    best: tuple[int, str] | None = None
    for alias, key in METRIC_ALIASES.items():
        if alias in question and key in TIMESERIES_METRIC_KEYS:
            if best is None or len(alias) > best[0]:
                best = (len(alias), key)
    if best:
        return best[1]
    return None


# 점수가 같을 때의 우선순위. 앞에 있을수록 우선한다.
# '집행률과 인구 유출의 관계' 처럼 여러 신호가 섞인 질문에서, 관계를 묻는 질문은
# 집행 현황 조회가 아니라 인과분석으로 보내는 것이 맞다.
INTENT_TIE_BREAK = (
    INTENT_CAUSAL,
    INTENT_PROPOSAL,
    INTENT_EVIDENCE,
    INTENT_COMPARISON,
    INTENT_FUND,
    INTENT_TIMESERIES,
)


def _score_intents(question: str) -> dict[str, tuple[float, list[str]]]:
    lowered = question.lower()
    scores: dict[str, tuple[float, list[str]]] = {}
    for intent, keywords in INTENT_KEYWORDS.items():
        matched = [keyword for keyword in keywords if keyword in lowered]
        # '집행률'이 걸렸으면 그 부분문자열인 '집행'은 따로 세지 않는다. 이중계상 방지.
        matched = [
            keyword
            for keyword in matched
            if not any(other != keyword and keyword in other for other in matched)
        ]
        total = sum(keywords[keyword] for keyword in matched)
        if total:
            scores[intent] = (total, matched)
    return scores


def route_with_rules(question: str) -> Route:
    text = question.strip()
    if not text:
        return Route(
            intent=INTENT_OUT_OF_SCOPE,
            intent_label_ko=INTENT_LABELS_KO[INTENT_OUT_OF_SCOPE],
            out_of_scope_reason="질문이 비어 있습니다.",
        )

    regions, group = extract_regions(text)
    year = extract_year(text)
    metric = extract_metric(text)

    outside_region = next((r for r in OUT_OF_SCOPE_REGIONS if r in text), None)
    if outside_region and not regions:
        return Route(
            intent=INTENT_OUT_OF_SCOPE,
            intent_label_ko=INTENT_LABELS_KO[INTENT_OUT_OF_SCOPE],
            confidence=0.9,
            out_of_scope_reason=f"'{outside_region}' 는 이 데이터에 없는 지역입니다. {SCOPE_STATEMENT}",
        )
    outside_topic = next((t for t in OUT_OF_SCOPE_TOPICS if t in text), None)
    if outside_topic:
        return Route(
            intent=INTENT_OUT_OF_SCOPE,
            intent_label_ko=INTENT_LABELS_KO[INTENT_OUT_OF_SCOPE],
            confidence=0.9,
            out_of_scope_reason=f"'{outside_topic}' 는 이 서비스가 다루는 주제가 아닙니다. {SCOPE_STATEMENT}",
        )

    scores = _score_intents(text)
    if not scores:
        return Route(
            intent=INTENT_OUT_OF_SCOPE,
            intent_label_ko=INTENT_LABELS_KO[INTENT_OUT_OF_SCOPE],
            regions=regions,
            year=year,
            metric=metric,
            confidence=0.5,
            out_of_scope_reason=f"질문에서 다룰 수 있는 주제를 찾지 못했습니다. {SCOPE_STATEMENT}",
        )

    intent, (score, matched) = max(
        scores.items(),
        key=lambda kv: (kv[1][0], -INTENT_TIE_BREAK.index(kv[0])),
    )

    # 지역이 2개 이상이면 비교 의도로 본다. 단, 기금·인과 신호가 훨씬 강하면 그대로 둔다.
    if len(regions) >= 2 and intent == INTENT_TIMESERIES:
        intent = INTENT_COMPARISON
        matched = [*matched, "지역 2개 이상"]

    total = sum(value for value, _ in scores.values()) or 1.0
    return Route(
        intent=intent,
        intent_label_ko=INTENT_LABELS_KO[intent],
        regions=regions,
        region_group=group,
        year=year,
        metric=metric,
        fund_id="local-extinction" if intent == INTENT_FUND else None,
        confidence=min(score / total, 1.0),
        matched_keywords=matched,
    )
