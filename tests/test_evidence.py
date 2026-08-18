"""5단계: 근거 문서 파싱, 인덱싱, 검색."""

from __future__ import annotations

import json

import pytest

from app.data.evidence import parse_register
from app.services import evidence_search
from tests.conftest import PDFS_AVAILABLE, requires_pdfs


def test_projects_parsed_from_register(client):
    body = client.get("/api/evidence/projects").json()
    projects = body["data"]["projects"]
    assert len(projects) == 3
    by_name = {p["project_name"]: p for p in projects}

    korean_diaspora = by_name["고려인 등 재외동포 이주정착 지원사업"]
    assert korean_diaspora["grade"] == "A"
    assert korean_diaspora["fund_million_krw"] == 1600.0
    assert korean_diaspora["period_start"] == "2023-04"
    assert korean_diaspora["period_end"] is None  # 지속
    assert korean_diaspora["usable_for_performance_2017_2024"] is True

    culture = by_name["생활문화충전소 놀 조성사업"]
    assert culture["grade"] == "C"
    assert culture["fund_million_krw"] == 6000.0
    assert culture["period_start"] == "2025-01"
    assert culture["usable_for_performance_2017_2024"] is False

    youth_farm = by_name["청년농촌보금자리조성사업"]
    assert youth_farm["grade"] == "C"
    assert youth_farm["fund_million_krw"] == 4000.0
    assert youth_farm["period_start"] == "2025-01"
    assert youth_farm["usable_for_performance_2017_2024"] is False


@requires_pdfs
def test_projects_linked_to_source_pdfs(client):
    projects = client.get("/api/evidence/projects").json()["data"]["projects"]
    assert all(p["source_document"] and p["source_document"].endswith(".pdf") for p in projects)
    assert len({p["source_document"] for p in projects}) == 3


def test_grade_criteria_exposed(client):
    body = client.get("/api/evidence/projects").json()
    assert set(body["data"]["grade_criteria"]) == {"A", "B", "C"}
    assert "2025년 이후" in body["data"]["grade_criteria"]["C"]


def test_search_returns_grade_and_source(client):
    body = client.get("/api/evidence/search", params={"q": "청년 주거", "top_k": 5}).json()
    hits = body["data"]["hits"]
    assert hits
    for hit in hits:
        assert hit["grade"] in {"A", "B", "C"}
        assert hit["document"]
        assert hit["excerpt"]
        assert hit["score"] > 0
        if hit["document_kind"] == "pdf":
            assert hit["page"] and hit["page"] >= 1


@requires_pdfs
def test_search_finds_relevant_project(client):
    hits = client.get(
        "/api/evidence/search", params={"q": "고려인 재외동포 이주정착", "top_k": 3}
    ).json()["data"]["hits"]
    assert any("고려인" in (h["project_name"] or "") for h in hits)


@requires_pdfs
def test_hybrid_lanes_both_contribute(client):
    hits = client.get("/api/evidence/search", params={"q": "문화회관 리모델링"}).json()["data"]["hits"]
    top = hits[0]
    assert top["keyword_score"] > 0
    assert top["vector_score"] > 0
    assert top["score"] == pytest.approx(0.5 * top["keyword_score"] + 0.5 * top["vector_score"], abs=1e-5)


def test_performance_purpose_excludes_grade_c(client):
    """등급 C 사업이 2017~2024 성과 근거로 인용되지 않게 한다."""
    body = client.get(
        "/api/evidence/search",
        params={"q": "청년 주거", "purpose": "performance_2017_2024", "top_k": 10},
    ).json()
    hits = body["data"]["hits"]
    if PDFS_AVAILABLE:
        # PDF가 없으면 등록부 3건만 남아 '청년 주거'에 걸리는 A등급 청크가 없을 수 있다.
        assert hits
    assert all(hit["grade"] != "C" for hit in hits)
    assert all(hit["usable_for_performance_2017_2024"] is not False for hit in hits)
    assert body["data"]["excluded_grade_c_count"] > 0
    assert any("등급 C" in note for note in body["meta"]["notes"])


def test_all_purpose_keeps_grade_c(client):
    hits = client.get(
        "/api/evidence/search", params={"q": "청년 주거", "purpose": "all", "top_k": 10}
    ).json()["data"]["hits"]
    assert any(hit["grade"] == "C" for hit in hits)


def test_grade_filter(client):
    hits = client.get(
        "/api/evidence/search", params={"q": "사업", "grade": "A", "top_k": 10}
    ).json()["data"]["hits"]
    assert hits and all(hit["grade"] == "A" for hit in hits)


def test_invalid_grade_and_purpose(client):
    bad_grade = client.get("/api/evidence/search", params={"q": "청년", "grade": "Z"})
    assert bad_grade.status_code == 422
    assert bad_grade.json()["error"]["allowed_values"] == ["A", "B", "C"]

    bad_purpose = client.get("/api/evidence/search", params={"q": "청년", "purpose": "past"})
    assert bad_purpose.status_code == 422
    assert bad_purpose.json()["error"]["code"] == "invalid_purpose"


def test_top_k_is_respected(client):
    hits = client.get("/api/evidence/search", params={"q": "사업", "top_k": 2}).json()["data"]["hits"]
    assert len(hits) <= 2


def test_search_is_deterministic(client):
    first = client.get("/api/evidence/search", params={"q": "청년 정착", "top_k": 5}).json()
    second = client.get("/api/evidence/search", params={"q": "청년 정착", "top_k": 5}).json()
    assert [h["chunk_id"] for h in first["data"]["hits"]] == [
        h["chunk_id"] for h in second["data"]["hits"]
    ]


def test_index_is_cached_to_local_file():
    from app.config import get_settings

    evidence_search.get_index(force_rebuild=True)
    settings = get_settings()
    path = settings.resolve(settings.index_dir) / evidence_search.INDEX_FILENAME
    assert path.exists()
    cached = json.loads(path.read_text(encoding="utf-8"))
    assert cached["index_version"] == evidence_search.INDEX_VERSION
    assert len(cached["chunks"]) >= 3  # 최소한 등록부 사업 3건
    # 지문이 그대로면 PDF를 다시 파싱하지 않는다
    assert evidence_search.load_chunks() == [
        evidence_search.Chunk(**c) for c in cached["chunks"]
    ]


def test_period_parsing_variants(tmp_path):
    md = tmp_path / "register.md"
    md.write_text(
        "\n".join(
            [
                "## 등록 결과",
                "",
                "| 지역 | 사업명 | 기금액 | 공식 사업기간 | 확인된 추진근거 | 등급 | 사용 판정 |",
                "|---|---|---:|---|---|---|---|",
                "| 제천시 | 지속형 | 1,600백만원 | 2023.04~지속 | 기록 | A | 사용 |",
                "| 보은군 | 연단위 | 500백만원 | 2025~2027 | 기록 | C | 제외 |",
                "| 옥천군 | 월단위 | 60백만원 | 2022.03~2024.12 | 기록 | B | 카드 |",
            ]
        ),
        encoding="utf-8",
    )
    records = parse_register(md)
    assert [r.period_start for r in records] == ["2023-04", "2025-01", "2022-03"]
    assert [r.period_end for r in records] == [None, "2027-12", "2024-12"]
    assert [r.grade for r in records] == ["A", "C", "B"]
    assert [r.usable_for_performance_2017_2024 for r in records] == [True, False, True]
