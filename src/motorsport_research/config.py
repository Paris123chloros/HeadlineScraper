"""Validated settings shared by the CLI, web application, and future worker."""

from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AnyHttpUrl, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    ollama_base_url: AnyHttpUrl = AnyHttpUrl("http://127.0.0.1:11434")
    ollama_model: str = "qwen3.5-instruct:4b"
    ollama_timeout_seconds: float = Field(default=5, gt=0, le=120)
    report_timezone: str = "Europe/Athens"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    data_dir: Path = Path("data")
    source_catalogue: Path = Path("config/sources.yaml")

    @field_validator("ollama_base_url")
    @classmethod
    def validate_endpoint(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password or value.query or value.fragment:
            raise ValueError("use an HTTP(S) base URL without credentials, query, or fragment")
        return value

    @field_validator("ollama_model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value or any(character.isspace() for character in value):
            raise ValueError("provide a nonempty Ollama model tag without whitespace")
        return value

    @field_validator("report_timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("use a valid IANA timezone, such as Europe/Athens or UTC") from None
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        return value.upper() if isinstance(value, str) else value


class ConfigurationError(ValueError):
    """Configuration error safe to display without echoing environment values."""


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        details = "; ".join(
            f"{'.'.join(map(str, item['loc'])).upper()}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )
        raise ConfigurationError(f"Invalid configuration. {details}") from None
