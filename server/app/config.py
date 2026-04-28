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

    # OpenAI (supports OpenAI-compatible proxies via openai_base_url)
    openai_api_key: str = ""
    openai_base_url: str = ""  # empty = use official https://api.openai.com
    openai_model: str = "gpt-4o"
    openai_classifier_model: str = "gpt-4o-mini"

    # Business context — determines which <brand>.business.md is loaded for LLM prompts
    active_business: str = "premlogin"

    # Optional SOCKS5 / HTTP proxy URL for outbound SMTP traffic. Leave blank
    # to connect directly. Set this when the host machine sits behind a proxy
    # that intercepts DNS but doesn't forward SMTP (e.g. Clash/v2ray fake-ip
    # mode in mainland China). Examples:
    #   socks5://127.0.0.1:7890   (Clash default)
    #   http://127.0.0.1:7890     (HTTP CONNECT)
    smtp_proxy: str | None = None

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
    # Server 酱 SendKey for WeChat push (sct.ftqq.com). Used as fallback when
    # the SystemSettings DB row has no webhook_serverchan configured.
    serverchan_send_key: str = ""

    # Brave Search API (powers Instagram scraper's Google-Dork entry)
    brave_search_api_key: str = ""

    # Apify API (powers Instagram profile data extraction — bypasses IG's
    # require_login wall on contact email / external_url that no Playwright
    # SSR scrape can pierce). Sign up at https://apify.com to get a token,
    # ~$5 free credit covers ~50-100 profile scrapes. Without this token the
    # Instagram scraper falls back to the SSR-only Playwright path with
    # ~5-10% email hit rate; with it, hit rate climbs to 40-60%+ because
    # Apify's actor solves the contact_email field that IG hides behind
    # login.
    apify_api_token: str = ""
    apify_ig_actor: str = "apify~instagram-profile-scraper"
    # TikTok scraper actor. Default is clockworks/tiktok-scraper (cheap list
    # actor at $0.0037/result; we extract emails locally from bio text).
    # Switched from jurassic_jove/tiktok-email-scraper on 2026-04-26 — old
    # actor cost ~$0.03/result and its scrapeEmails=true was leaking
    # third-party emails (johnappleseed@, support@clickbank, etc.) from
    # external bio link landing pages. Same APIFY_API_TOKEN works for both.
    apify_tiktok_actor: str = "clockworks~tiktok-scraper"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
