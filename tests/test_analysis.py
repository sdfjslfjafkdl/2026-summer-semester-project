"""4단계 완료 기준:
- baseline JSON을 v1 아티팩트로 변환해 정상 반환
- 필드가 빠진 아티팩트에서 명확한 검증 오류
"""

from __future__ import annotations

import json

import pytest

from app.schemas.artifacts import DidArtifact
from app.services.artifacts import ArtifactStore, DID_FILENAME


def test_did_returns_baseline_values(client):
    body = client.get("/api/analysis/did").json()
    effect = body["data"]["effect"]
    significance = body["data"]["significance"]

    assert effect["coefficient"] == pytest.approx(0.9496181198273366)
    assert effect["unit"] == "명/천명"
    assert effect["standard_error"] == pytest.approx(1.2447543537087846)
    assert effect["ci_95_low"] == pytest.approx(-1.823867416850271)
    assert effect["ci_95_high"] == pytest.approx(3.7231036565049442)
    assert significance["p_value"] == pytest.approx(0.46314203447465774)


def test_did_is_not_reported_as_significant(client):
    """p=0.4631 을 유의한 결과처럼 서술하지 않는다."""
    body = client.get("/api/analysis/did").json()
    significance = body["data"]["significance"]
    assert significance["is_significant"] is False
    assert significance["label_ko"] == "통계적으로 유의하지 않음"
    assert "말할 수 없습니다" in significance["statement_ko"]
    assert "유의하지" in significance["label_ko"]
    # 신뢰구간이 0을 포함한다는 사실도 함께 알린다
    assert body["data"]["effect"]["ci_95_low"] < 0 < body["data"]["effect"]["ci_95_high"]


def test_did_design_follows_panel_not_mockup(client):
    """목업의 3개 대 3개 구성이 아니라 실제 패널 설계(6 대 5)를 따른다."""
    design = client.get("/api/analysis/did").json()["data"]["design"]
    assert design["treated_region_count"] == 6
    assert design["control_region_count"] == 5
    assert set(design["treated_regions"]) == {"제천시", "보은군", "옥천군", "영동군", "괴산군", "단양군"}
    assert set(design["control_regions"]) == {"청주시", "충주시", "증평군", "진천군", "음성군"}
    assert design["treatment_start"] == "2022-01"
    assert design["n_observations"] == 1056
    assert design["n_clusters"] == 11


def test_did_carries_cautions(client):
    body = client.get("/api/analysis/did").json()
    assert len(body["data"]["interpretation_cautions"]) >= 2
    notes = " ".join(body["meta"]["notes"])
    assert "명/천명" in notes and "%p" in notes


def test_did_group_means_match_baseline(client):
    means = client.get("/api/analysis/did").json()["data"]["group_means"]
    assert means["treated_pre_mean"] == pytest.approx(-4.710246832861368)
    assert means["treated_post_mean"] == pytest.approx(-3.810925393560115)
    assert means["control_pre_mean"] == pytest.approx(0.21198316302062653)
    assert means["control_post_mean"] == pytest.approx(0.1616864824945462)
    assert means["simple_did_mean_difference"] == pytest.approx(0.9496181198273335)


def test_validation_overall_and_by_region(client):
    body = client.get("/api/analysis/validation").json()
    overall = body["data"]["overall"]
    assert overall["mae"] == pytest.approx(3.1711446949051396)
    assert overall["rmse"] == pytest.approx(4.265151872241913)
    assert overall["n_observations"] == 132
    rows = body["data"]["by_region"]
    assert len(rows) == 11
    assert {r["region"] for r in rows} >= {"제천시", "청주시"}
    assert all(r["n_months"] == 12 for r in rows)
    assert "does not establish the causal effect" in overall["interpretation"]


# ── 아티팩트 검증 ────────────────────────────────────────────────


def _artifact_dict() -> dict:
    from app.config import get_settings

    settings = get_settings()
    path = settings.resolve(settings.artifact_dir) / DID_FILENAME
    return json.loads(path.read_text(encoding="utf-8"))


def _store_with(tmp_path, payload: dict) -> ArtifactStore:
    path = tmp_path / DID_FILENAME
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    store: ArtifactStore = ArtifactStore(DID_FILENAME, DidArtifact)
    store.path = path  # type: ignore[misc]
    return store


def test_missing_field_reports_which_field(tmp_path, monkeypatch):
    from app.errors import ApiError
    from app.services import artifacts as artifacts_module

    payload = _artifact_dict()
    del payload["p_value"]
    del payload["treated_regions"]
    (tmp_path / DID_FILENAME).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(
        type(artifacts_module.did_store), "path", property(lambda self: tmp_path / DID_FILENAME)
    )
    store = artifacts_module.ArtifactStore(DID_FILENAME, DidArtifact)
    with pytest.raises(ApiError) as exc:
        store.load()

    assert exc.value.body.code == "artifact_schema_mismatch"
    fields = {v["field"] for v in exc.value.body.details["violations"]}
    assert {"p_value", "treated_regions"} <= fields


def test_artifact_claiming_false_significance_is_rejected():
    """p=0.4631 인데 is_significant=true 인 아티팩트는 적재를 거부한다."""
    payload = _artifact_dict()
    payload["is_significant"] = True
    payload["significance_label_ko"] = "통계적으로 유의함"
    with pytest.raises(ValueError, match="유의성 표기"):
        DidArtifact.model_validate(payload)


def test_artifact_with_inconsistent_ci_is_rejected():
    payload = _artifact_dict()
    payload["ci_95"] = [2.0, 3.0]  # 계수 0.9496 이 구간 밖
    with pytest.raises(ValueError, match="ci_95"):
        DidArtifact.model_validate(payload)


def test_artifact_with_overlapping_groups_is_rejected():
    payload = _artifact_dict()
    payload["control_regions"] = [*payload["control_regions"], "제천시"]
    with pytest.raises(ValueError, match="같은 지역"):
        DidArtifact.model_validate(payload)


def test_unknown_extra_field_is_rejected():
    payload = _artifact_dict()
    payload["mystery_number"] = 42
    with pytest.raises(ValueError):
        DidArtifact.model_validate(payload)


def test_artifact_reloads_when_file_changes(tmp_path, monkeypatch):
    """파일이 갱신되면 재기동 없이 반영된다."""
    import os

    from app.services import artifacts as artifacts_module

    path = tmp_path / DID_FILENAME
    payload = _artifact_dict()
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    store = artifacts_module.ArtifactStore(DID_FILENAME, DidArtifact)
    monkeypatch.setattr(type(store), "path", property(lambda self: path))

    first = store.load()
    assert first.coefficient == pytest.approx(0.9496181198273366)

    payload["coefficient"] = 1.5
    payload["ci_95"] = [-1.0, 4.0]
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.utime(path, (path.stat().st_atime, path.stat().st_mtime + 10))

    second = store.load()
    assert second.coefficient == pytest.approx(1.5)


def test_missing_artifact_file_returns_actionable_error(tmp_path, monkeypatch):
    from app.errors import ApiError
    from app.services import artifacts as artifacts_module

    store = artifacts_module.ArtifactStore(DID_FILENAME, DidArtifact)
    monkeypatch.setattr(type(store), "path", property(lambda self: tmp_path / "nope.json"))
    with pytest.raises(ApiError) as exc:
        store.load()
    assert exc.value.body.code == "artifact_missing"
    assert "build_artifacts" in exc.value.body.message
