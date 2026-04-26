from typing import Optional
from pydantic import BaseModel, Field, HttpUrl


class FollowUpSettingsNested(BaseModel):
    enabled: Optional[bool] = None
    interval_days: Optional[int] = Field(None, ge=1, le=365)
    max_count: Optional[int] = Field(None, ge=1, le=50)
    hour_utc: Optional[int] = Field(None, ge=0, le=23)


class SettingsOut(BaseModel):
    # follow-up strategy
    follow_up_enabled: bool
    interval_days: int
    max_count: int
    hour_utc: int
    # scrape
    scrape_concurrency: int
    # webhooks
    webhook_feishu: str
    webhook_slack: str
    # apify per-platform config
    # tokens are MASKED on output (e.g. "****abcd"); full value only on PUT.
    # The *_token_set boolean tells the UI whether DB has a value, since the
    # masked string itself is unsuitable for "configured?" checks.
    apify_tiktok_token: str
    apify_tiktok_token_set: bool
    apify_tiktok_actor: str
    apify_ig_token: str
    apify_ig_token_set: bool
    apify_ig_actor: str


class SettingsUpdate(BaseModel):
    # follow-up strategy (optional)
    follow_up_enabled: Optional[bool] = None
    interval_days: Optional[int] = Field(None, ge=1, le=365)
    max_count: Optional[int] = Field(None, ge=1, le=50)
    hour_utc: Optional[int] = Field(None, ge=0, le=23)
    # scrape (optional)
    scrape_concurrency: Optional[int] = Field(None, ge=1, le=50)
    # webhooks (optional)
    webhook_feishu: Optional[str] = None
    webhook_slack: Optional[str] = None
    # apify per-platform config (optional). Token == "" clears it; token == None
    # leaves it unchanged. Same convention for actor. This lets the UI ship a
    # PUT with only the fields the user touched.
    apify_tiktok_token: Optional[str] = None
    apify_tiktok_actor: Optional[str] = Field(None, max_length=255)
    apify_ig_token: Optional[str] = None
    apify_ig_actor: Optional[str] = Field(None, max_length=255)


class TestApifyActorRequest(BaseModel):
    platform: str = Field(..., description="tiktok | instagram")
    token: Optional[str] = Field(
        None,
        description=(
            "Apify token to test. If omitted, server uses the currently saved "
            "DB value for this platform (or env var fallback)."
        ),
    )
    actor: Optional[str] = Field(
        None,
        description=(
            "Apify actor ID to test. If omitted, server uses the currently saved "
            "DB value for this platform (or env var fallback)."
        ),
    )


class TestApifyActorResponse(BaseModel):
    success: bool
    platform: str
    actor: str
    message: str
    actor_title: Optional[str] = None
    actor_username: Optional[str] = None
