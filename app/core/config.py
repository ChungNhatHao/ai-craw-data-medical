from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: Literal["local", "test", "staging", "production"] = "local"
    log_level: str = "INFO"
    log_json: bool = False

    database_path: Path = Path("state/crawler.db")
    migrations_path: Path = Path("migrations")
    output_root: Path = Path("output")
    session_root: Path = Path("state/sessions")

    browser_headless: bool = True
    browser_navigation_timeout_ms: PositiveInt = Field(default=30_000)
    browser_selector_timeout_ms: PositiveInt = Field(default=10_000)
    navigation_max_hops_per_item: PositiveInt = Field(default=12)
    navigation_max_same_fingerprint: PositiveInt = Field(default=3)
    navigation_max_no_progress: PositiveInt = Field(default=2)
    disease_detail_confidence_threshold: float = Field(default=0.80, ge=0, le=1)
    crawl_max_items: PositiveInt = Field(default=1_000)
    crawl_max_pages: PositiveInt = Field(default=100)
    discovery_max_no_new_rounds: PositiveInt = Field(default=2)
    category_hard_max_depth: PositiveInt = Field(default=8, le=8)
    category_hard_max_nodes: PositiveInt = Field(default=250, le=250)
    category_hard_max_diseases: PositiveInt = Field(default=250, le=250)
    fetch_max_attempts: PositiveInt = Field(default=3)
    fetch_retry_base_seconds: float = Field(default=2, ge=0)
    fetch_retry_max_seconds: float = Field(default=60, ge=0)
    capture_screenshot: bool = True
    parse_timeout_seconds: float = Field(default=90, gt=0)
    parse_max_attempts: PositiveInt = Field(default=3)
    parse_retry_base_seconds: float = Field(default=2, ge=0)
    parse_retry_max_seconds: float = Field(default=10, ge=0)
    parse_max_model_calls: PositiveInt = Field(default=40)
    parse_max_input_chars: PositiveInt = Field(default=200_000)

    agentic_discovery_enabled: bool = False
    agentic_parsing_enabled: bool = False
    ai_normalization_enabled: bool = False
    gemini_api_key: SecretStr | None = None
    gemini_navigation_model: str = "gemini-3.5-flash-lite"
    gemini_detector_model: str = "gemini-3.5-flash-lite"
    gemini_extraction_model: str = "gemini-3.5-flash-lite"
    gemini_normalization_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: float = Field(default=30, gt=0)
    gemini_max_retries: int = Field(default=3, ge=0)
    gemini_retry_base_seconds: float = Field(default=20, ge=0)
    gemini_retry_max_seconds: float = Field(default=60, ge=0)
    gemini_max_calls_per_job: PositiveInt = Field(default=100)
    gemini_max_input_chars: PositiveInt = Field(default=30_000)
    gemini_disease_confidence_threshold: float = Field(default=0.85, ge=0, le=1)

    genre_manuals_base_url: HttpUrl = HttpUrl(
        "https://www.genre-manuals.com/sites/CLUE/home.html"
    )
    genre_manuals_username: SecretStr | None = None
    genre_manuals_password: SecretStr | None = None

    def ensure_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.session_root.mkdir(parents=True, exist_ok=True)

    def require_genre_manuals_credentials(self) -> "Credentials":
        if self.genre_manuals_username is None or self.genre_manuals_password is None:
            raise ValueError(
                "GENRE_MANUALS_USERNAME and GENRE_MANUALS_PASSWORD must be set"
            )
        return Credentials(
            username=self.genre_manuals_username,
            password=self.genre_manuals_password,
        )

    def secret_values(self) -> frozenset[str]:
        values = (
            self.genre_manuals_username,
            self.genre_manuals_password,
            self.gemini_api_key,
        )
        return frozenset(
            secret.get_secret_value()
            for secret in values
            if secret is not None and secret.get_secret_value()
        )


class Credentials(BaseModel):
    model_config = ConfigDict(frozen=True)

    username: SecretStr
    password: SecretStr


@lru_cache
def get_settings() -> Settings:
    return Settings()
