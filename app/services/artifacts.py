"""아티팩트 로더.

파일이 갱신되면 재기동 없이 반영되도록, 요청 시 mtime 을 확인해 바뀌었을 때만 다시 읽는다.
검증에 실패하면 어떤 필드가 왜 어긋났는지 그대로 드러내는 오류를 낸다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.errors import ApiError
from app.schemas.artifacts import DidArtifact, ValidationArtifact

DID_FILENAME = "did_twfe_v1.json"
VALIDATION_FILENAME = "oot_validation_v1.json"

T = TypeVar("T", bound=BaseModel)


@dataclass
class _CacheEntry(Generic[T]):
    mtime: float
    model: T


class ArtifactStore(Generic[T]):
    def __init__(self, filename: str, model_type: type[T]) -> None:
        self.filename = filename
        self.model_type = model_type
        self._cache: _CacheEntry[T] | None = None

    @property
    def path(self) -> Path:
        settings = get_settings()
        return settings.resolve(settings.artifact_dir) / self.filename

    def load(self) -> T:
        path = self.path
        if not path.exists():
            raise ApiError(
                status_code=503,
                code="artifact_missing",
                message=(
                    f"분석 결과 아티팩트가 없습니다: {self.filename}. "
                    "scripts/build_artifacts.py 로 생성하거나 모델링 담당자의 산출물을 "
                    "data/artifacts/ 에 넣어 주세요."
                ),
                details={"expected_path": str(path)},
            )

        mtime = path.stat().st_mtime
        if self._cache is not None and self._cache.mtime == mtime:
            return self._cache.model

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ApiError(
                status_code=500,
                code="artifact_not_json",
                message=f"아티팩트 {self.filename} 이 올바른 JSON이 아닙니다: {exc}",
                details={"path": str(path)},
            ) from exc

        try:
            model = self.model_type.model_validate(raw)
        except ValidationError as exc:
            raise ApiError(
                status_code=500,
                code="artifact_schema_mismatch",
                message=(
                    f"아티팩트 {self.filename} 이 v1 스키마와 맞지 않습니다. "
                    f"어긋난 항목 {len(exc.errors())}건을 details 에 담았습니다."
                ),
                details={
                    "path": str(path),
                    "violations": [
                        {
                            "field": ".".join(str(part) for part in error["loc"]) or "(root)",
                            "problem": error["msg"],
                            "type": error["type"],
                        }
                        for error in exc.errors()
                    ],
                },
            ) from exc

        self._cache = _CacheEntry(mtime=mtime, model=model)
        return model

    def loaded_at_mtime(self) -> float | None:
        return self._cache.mtime if self._cache else None


did_store: ArtifactStore[DidArtifact] = ArtifactStore(DID_FILENAME, DidArtifact)
validation_store: ArtifactStore[ValidationArtifact] = ArtifactStore(
    VALIDATION_FILENAME, ValidationArtifact
)
