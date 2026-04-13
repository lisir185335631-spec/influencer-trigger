from pydantic_settings import BaseSettings
from functools import lru_cache


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
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Webhook notifications
    feishu_webhook_url: str = ""
    slack_webhook_url: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
