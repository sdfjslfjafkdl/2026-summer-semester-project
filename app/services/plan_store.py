"""작성 중인 투자계획서 보관소.

메모리에 두고 가능하면 파일로도 남긴다. 배포 환경의 볼륨은 비어 있거나 쓰기가 막힐 수
있으므로(근거 검색 캐시와 같은 사정), 저장 실패가 요청 실패로 이어지지 않게 한다.
다만 캐시와 달리 계획서는 사람이 쓴 내용이라 잃으면 복구할 수 없다.
그래서 저장에 실패하면 응답 notes 로 그 사실을 알린다.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.errors import ApiError

logger = logging.getLogger(__name__)

KST = timezone.utc  # 표기용. 시각은 ISO 8601 로만 쓴다.


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


@dataclass
class StoredSection:
    section_id: str
    content: str | None = None
    source: str = "none"
    status: str = "placeholder"
    data_points: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    version: int = 1
    updated_at: str = field(default_factory=now_iso)


@dataclass
class StoredPlan:
    plan_id: str
    region: str
    year: int
    version: int = 1
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    sections: dict[str, StoredSection] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    called_endpoints: list[str] = field(default_factory=list)
    # 초안을 만들 때 호출한 Layer 1 결과. 이후 수정에서도 수치 검증의 기준이 된다.
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    # 사람이 직접 넣은 숫자. 도구 결과에 없어도 허용하되 출처를 사람 입력으로 표시한다.
    human_numbers: list[float] = field(default_factory=list)
    persisted: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sections"] = {k: asdict(v) for k, v in self.sections.items()}
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "StoredPlan":
        sections = {
            key: StoredSection(**value) for key, value in (payload.get("sections") or {}).items()
        }
        return cls(**{**payload, "sections": sections})


_plans: dict[str, StoredPlan] = {}


def _plan_dir() -> Path:
    settings = get_settings()
    directory = settings.resolve(settings.plan_dir)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("계획서 저장 디렉터리를 만들지 못했습니다(%s). 메모리에만 보관합니다.", exc)
    return directory


def make_plan_id(region: str, year: int) -> str:
    existing = sum(1 for p in _plans.values() if p.region == region and p.year == year)
    return f"plan_{region}_{year}_{existing + 1:02d}"


def save(plan: StoredPlan) -> StoredPlan:
    plan.updated_at = now_iso()
    _plans[plan.plan_id] = plan
    path = _plan_dir() / f"{plan.plan_id}.json"
    try:
        path.write_text(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        plan.persisted = True
    except OSError as exc:
        plan.persisted = False
        logger.warning("계획서 %s 를 파일로 저장하지 못했습니다(%s). 메모리에만 있습니다.", plan.plan_id, exc)
    return plan


def get(plan_id: str) -> StoredPlan:
    plan = _plans.get(plan_id)
    if plan is not None:
        return plan

    path = _plan_dir() / f"{plan_id}.json"
    if path.exists():
        try:
            plan = StoredPlan.from_dict(json.loads(path.read_text(encoding="utf-8")))
            _plans[plan_id] = plan
            return plan
        except (json.JSONDecodeError, TypeError, OSError) as exc:
            logger.warning("계획서 %s 를 읽지 못했습니다: %s", plan_id, exc)

    raise ApiError(
        status_code=404,
        code="unknown_plan",
        message=(
            f"'{plan_id}' 계획서를 찾을 수 없습니다. "
            "POST /api/plan/draft 로 먼저 초안을 만들어 주세요. "
            "서버가 재시작되었고 저장 볼륨이 없으면 이전 계획서는 사라집니다."
        ),
        field="plan_id",
        allowed_values=sorted(_plans),
    )


def record_history(plan: StoredPlan, action: str, changed: list[str], note: str | None = None) -> None:
    plan.history.append(
        {
            "version": plan.version,
            "created_at": now_iso(),
            "action": action,
            "changed_sections": changed,
            "note": note,
        }
    )


def reset_for_tests() -> None:
    _plans.clear()
