from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./feedback.db"
    frontend_origin: str = "http://localhost:5173"
    upload_max_bytes: int = 5 * 1024 * 1024
    llm_provider: str = "rule"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    clustering_threshold: float = Field(default=0.30, ge=0, le=1)
    priority_weight_frequency: float = Field(default=0.30, ge=0)
    priority_weight_severity: float = Field(default=0.25, ge=0)
    priority_weight_recency: float = Field(default=0.15, ge=0)
    priority_weight_negative_sentiment: float = Field(default=0.20, ge=0)
    priority_weight_rating: float = Field(default=0.10, ge=0)

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[3] / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_priority_weights(self):
        weights = (
            self.priority_weight_frequency,
            self.priority_weight_severity,
            self.priority_weight_recency,
            self.priority_weight_negative_sentiment,
            self.priority_weight_rating,
        )
        if not any(weights):
            raise ValueError("At least one priority score weight must be greater than zero")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
