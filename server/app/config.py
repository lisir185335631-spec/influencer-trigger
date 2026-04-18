from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings

_INSECURE_KEYS = frozenset({
    "",
    "change-me-in-production",
    "your-super-secret-key-change-in-production",
    "your-secret-key",
    "change-me-32-byte-fernet-key-b64=",
    "your-fernet-encryption-key-here",
})


class Settings(BaseSettings):
    # App
    app_name: str = "Influencer Trigger"
    debug: bool = False

    # Database
    database_url: str = "sqlite+aiosqlite:///./data/influencer.db"

    # JWT
    secret_key: str = "change-me-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Encryption key for SMTP passwords (Fernet, 32-byte base64)
    encryption_key: str = "change-me-32-byte-fernet-key-b64="

    @field_validator("secret_key")
    @classmethod
    def secret_key_must_be_secure(cls, v: str) -> str:
        if v in _INSECURE_KEYS:
            raise ValueError(
                "SECRET_KEY must be set to a secure random value in .env. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        return v

    # OpenAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    openai_classifier_model: str = "gpt-4o-mini"

    # SendGrid
    sendgrid_api_key: str = ""

    # Mailgun
    mailgun_api_key: str = ""
    mailgun_domain: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"

    # CORS
    cors_origins: list[str] = ["http://localhost:6001", "http://127.0.0.1:6001"]

    # Webhook notifications
    feishu_webhook_url: str = ""
    slack_webhook_url: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
