from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .repository import project_root


class AppSettings(BaseSettings):
    """Runtime settings. Secrets are read from the environment, never source files."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="MPA_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "test", "production"] = "development"
    public_demo_only: bool = True
    database_url: str = Field(
        default_factory=lambda: f"sqlite:///{(project_root() / 'data' / 'runtime' / 'agent.db').as_posix()}"
    )

    auth_mode: Literal["demo", "oidc"] = "demo"
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_role_claim: str = "roles"

    llm_provider: Literal["offline", "openai_compatible"] = "offline"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-5-mini"
    llm_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 45.0

    upload_max_mb: int = 15
    hybrid_bm25_weight: float = 0.55
    hybrid_semantic_weight: float = 0.35
    hybrid_exact_weight: float = 0.10
    log_level: str = "INFO"

    @field_validator("upload_max_mb")
    @classmethod
    def validate_upload_limit(cls, value: int) -> int:
        if not 1 <= value <= 100:
            raise ValueError("upload_max_mb must be between 1 and 100")
        return value

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return "postgresql+psycopg://" + value.removeprefix("postgres://")
        if value.startswith("postgresql://"):
            return "postgresql+psycopg://" + value.removeprefix("postgresql://")
        return value

    @field_validator(
        "hybrid_bm25_weight", "hybrid_semantic_weight", "hybrid_exact_weight"
    )
    @classmethod
    def validate_weight(cls, value: float) -> float:
        if not 0 <= value <= 1:
            raise ValueError("retrieval weights must be between 0 and 1")
        return value

    @property
    def runtime_dir(self) -> Path:
        path = project_root() / "data" / "runtime"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def validate_production(self) -> None:
        problems: list[str] = []
        if self.environment == "production" and self.auth_mode != "oidc":
            problems.append("production requires MPA_AUTH_MODE=oidc")
        if self.auth_mode == "oidc":
            for name, value in {
                "MPA_OIDC_ISSUER": self.oidc_issuer,
                "MPA_OIDC_AUDIENCE": self.oidc_audience,
                "MPA_OIDC_JWKS_URL": self.oidc_jwks_url,
            }.items():
                if not value:
                    problems.append(f"{name} is required in OIDC mode")
        if self.llm_provider == "openai_compatible" and not self.llm_api_key:
            problems.append("MPA_LLM_API_KEY is required for the configured LLM provider")
        if problems:
            raise ValueError("; ".join(problems))


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    settings = AppSettings()
    settings.validate_production()
    return settings
