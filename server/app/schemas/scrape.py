from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


SUPPORTED_PLATFORMS = {"instagram", "youtube", "tiktok", "twitter", "facebook"}


class ScrapeTaskCreate(BaseModel):
    platforms: List[str] = Field(min_length=1)
    industry: str = Field(min_length=1, max_length=128)
    target_count: int = Field(default=50, ge=1, le=500)
    target_market: str | None = None
    competitor_brands: str | None = None

    def validate_platforms(self) -> "ScrapeTaskCreate":
        for p in self.platforms:
            if p not in SUPPORTED_PLATFORMS:
                raise ValueError(f"Unsupported platform: {p}")
        return self


class ScrapeTaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    platforms: str
    industry: str
    target_count: int
    status: str
    progress: int
    found_count: int
    valid_count: int
    error_message: str | None
    target_market: str | None = None
    search_keywords: str | None = None
    competitor_brands: str | None = None
    created_by: int | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScrapeInfluencerResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    nickname: Optional[str]
    email: str
    platform: Optional[str]
    profile_url: Optional[str]
    followers: Optional[int]
    industry: Optional[str]
    bio: Optional[str]
    status: str
    relevance_score: float | None = None
    match_reason: str | None = None
