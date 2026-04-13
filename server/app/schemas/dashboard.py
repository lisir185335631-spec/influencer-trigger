from pydantic import BaseModel


class DashboardStats(BaseModel):
    total_influencers: int
    new_this_week: int
    total_sent: int
    sent_this_week: int
    reply_rate: float          # replied / total_sent
    effective_reply_rate: float  # (interested+pricing) / total_sent
    conversion_rate: float     # collaborated / total_influencers


class TrendPoint(BaseModel):
    date: str   # YYYY-MM-DD
    sent: int
    replied: int


class DashboardTrends(BaseModel):
    data: list[TrendPoint]


class PlatformItem(BaseModel):
    platform: str
    count: int


class DashboardPlatformDistribution(BaseModel):
    data: list[PlatformItem]


class MailboxHealthItem(BaseModel):
    id: int
    email: str
    today_sent: int
    daily_limit: int
    total_sent: int
    bounce_rate: float
    status: str


class DashboardMailboxHealth(BaseModel):
    data: list[MailboxHealthItem]
