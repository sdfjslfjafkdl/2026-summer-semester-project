"""애플리케이션 설정. 모든 값은 .env 또는 환경변수로 주입한다."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"

    data_dir: Path = Path("data")
    panel_csv: Path = Path("data/raw/chungbuk_monthly_model_panel_2017_2024.csv")
    oot_region_csv: Path = Path("data/raw/chungbuk_oot_error_analysis_by_region.csv")
    panel_readme_md: Path = Path("data/raw/README_chungbuk_model_panel.md")
    evidence_register_md: Path = Path("data/raw/project_evidence_register_ko.md")
    evidence_pdf_dir: Path = Path("data/raw/evidence/pdf")
    artifact_dir: Path = Path("data/artifacts")
    index_dir: Path = Path("data/index")

    # NoDecode: 콤마 구분 문자열을 JSON으로 파싱하지 않고 아래 validator 가 처리한다.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["https://impact-advisor-ai.lovable.app"]
    )

    llm_enabled: bool = False
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-opus-5"
    llm_timeout_seconds: int = 20

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def resolve(self, path: Path) -> Path:
        """상대경로는 프로젝트 루트 기준으로 절대화한다."""
        return path if path.is_absolute() else (PROJECT_ROOT / path)

    @property
    def llm_active(self) -> bool:
        """LLM을 실제로 호출할 수 있는 상태인지. 키가 없으면 켜져 있어도 False."""
        return bool(self.llm_enabled and self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
