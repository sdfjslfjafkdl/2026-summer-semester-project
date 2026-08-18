"""chungbuk_baseline_results.json + OOT CSV → v1 아티팩트 변환.

모델링 담당자가 결과 JSON을 새로 주면 이 스크립트가 필요 없어진다. 지금은 1차 베이스라인을
v1 스키마로 옮겨 두는 용도다. 수치는 원본을 그대로 옮기며 반올림하지 않는다.

    uv run python scripts/build_artifacts.py
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.data.panel import CONTROL_REGIONS, TREATED_REGIONS, get_panel
from app.schemas.artifacts import DidArtifact, ValidationArtifact
from app.services.artifacts import DID_FILENAME, VALIDATION_FILENAME

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "artifacts"

BASELINE_JSON = RAW / "chungbuk_baseline_results.json"
OOT_CSV = RAW / "chungbuk_oot_error_analysis_by_region.csv"
README_MD = RAW / "README_chungbuk_model_panel.md"

ALPHA = 0.05

DID_CAUTIONS = [
    "이 결과는 기금 사업의 정확한 착수월과 사업별 집행시점, 전국·타시도 비교군이 없는 상태의 "
    "초기 탐색적 베이스라인이다.",
    "시군 11개와 군집 11개라는 작은 표본이므로 p값을 확정적 인과추론의 근거로 제시하면 안 된다.",
    "발표에서는 '효과 검증 파이프라인 및 1차 추정'으로 표현하고, 사업 착수월 확보 후 "
    "event-study·시차 DID로 고도화하는 것이 적절하다.",
    "기금 변수는 연도값을 12개월에 결합한 구조여서 월별 효과의 시점 해석에 제한이 있다.",
]


def build_did() -> DidArtifact:
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    did = baseline["did"]
    p_value = float(did["clustered_p_value"])
    is_significant = p_value < ALPHA

    return DidArtifact(
        artifact_version="v1",
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        generated_by="scripts/build_artifacts.py",
        method=did["type"],
        method_label_ko="양방향 고정효과 DID (TWFE)",
        outcome=did["outcome"],
        outcome_unit="명/천명",
        treated_regions=list(TREATED_REGIONS),
        control_regions=list(CONTROL_REGIONS),
        treatment_start="2022-01",
        sample_period="2017-01~2024-12",
        coefficient=float(did["twfe_coefficient"]),
        standard_error=float(did["clustered_standard_error"]),
        standard_error_type="clustered_by_municipality",
        t_statistic=float(did["clustered_t_statistic"]),
        p_value=p_value,
        ci_95=[float(x) for x in did["clustered_ci_95"]],
        alpha=ALPHA,
        is_significant=is_significant,
        significance_label_ko=(
            "통계적으로 유의함" if is_significant else "통계적으로 유의하지 않음"
        ),
        n_observations=int(did["n_observations"]),
        n_clusters=int(did["n_regions"]),
        r_squared=float(did["r_squared"]),
        n_model_parameters=int(did["n_model_parameters"]),
        treated_pre_mean=float(did["treated_pre_mean"]),
        treated_post_mean=float(did["treated_post_mean"]),
        control_pre_mean=float(did["control_pre_mean"]),
        control_post_mean=float(did["control_post_mean"]),
        simple_did_mean_difference=float(did["simple_did_mean_difference"]),
        interpretation_cautions=[did["standard_error_note"], *DID_CAUTIONS],
        source_files=[BASELINE_JSON.name, README_MD.name],
    )


def build_validation() -> ValidationArtifact:
    baseline = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))
    oot = baseline["out_of_time_validation"]
    by_region = pd.read_csv(OOT_CSV, encoding="utf-8-sig")
    by_region.columns = [c.strip() for c in by_region.columns]

    panel_regions = set(get_panel().region_names)
    missing = panel_regions - set(by_region["region"])
    if missing:
        raise SystemExit(f"OOT CSV에 빠진 지역이 있습니다: {sorted(missing)}")

    return ValidationArtifact(
        artifact_version="v1",
        generated_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        generated_by="scripts/build_artifacts.py",
        method=oot["type"],
        method_label_ko="계절 나이브(전년 동월) 예측",
        outcome="youth_net_migration_rate_per_1000",
        outcome_unit="명/천명",
        test_window=oot["test_window"],
        n_observations=int(oot["n_observations"]),
        mae=float(oot["mae"]),
        rmse=float(oot["rmse"]),
        mean_error_bias=float(oot["mean_error_bias"]),
        interpretation=oot["interpretation"],
        by_region=by_region.sort_values("mae").to_dict(orient="records"),  # type: ignore[arg-type]
        source_files=[BASELINE_JSON.name, OOT_CSV.name],
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for filename, artifact in (
        (DID_FILENAME, build_did()),
        (VALIDATION_FILENAME, build_validation()),
    ):
        path = OUT / filename
        path.write_text(
            json.dumps(artifact.model_dump(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"작성: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
