from datetime import datetime
from pydantic import BaseModel, ConfigDict


class TemplateCreate(BaseModel):
    name: str
    subject: str
    body_html: str
    industry: str | None = None
    style: str | None = None  # formal / casual / direct
    language: str = "en"


class TemplateUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    body_html: str | None = None
    industry: str | None = None
    style: str | None = None
    language: str | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: str
    body_html: str
    industry: str | None
    style: str | None
    language: str
    created_by: int | None
    created_at: datetime
    updated_at: datetime


class GenerateRequest(BaseModel):
    industry: str  # e.g. "fitness", "beauty", "gaming"


class GeneratedTemplate(BaseModel):
    name: str
    style: str  # formal / casual / direct
    subject: str
    body_html: str
