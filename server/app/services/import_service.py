"""
Import service: parse CSV/Excel, auto-map columns, validate emails, dedup, write to DB.
"""
import asyncio
import io
import logging
import re
from typing import Any

import dns.resolver
import pandas as pd
from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.influencer import Influencer, InfluencerPlatform
from app.schemas.import_ import (
    ColumnMappingItem,
    ImportConfirmResponse,
    ImportPreviewResponse,
)

logger = logging.getLogger(__name__)

# ── Column alias table ─────────────────────────────────────────────────────────

_FIELD_ALIASES: dict[str, list[str]] = {
    "email":       ["email", "邮箱", "邮件", "e-mail", "email address", "mail"],
    "nickname":    ["nickname", "昵称", "name", "名字", "用户名", "username", "handle"],
    "platform":    ["platform", "平台", "社交平台", "social platform", "channel"],
    "followers":   ["followers", "粉丝数", "粉丝", "follower count", "粉丝量", "fans"],
    "profile_url": ["profile_url", "主页链接", "主页", "url", "链接", "profile link", "profile", "link"],
    "industry":    ["industry", "行业", "类别", "分类", "category", "niche"],
}

_PLATFORM_VALUES = {"instagram", "youtube", "tiktok", "twitter", "facebook", "other"}

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# MX cache shared with scraper (simple in-process dict)
_mx_cache: dict[str, bool] = {}


def _detect_field(col: str) -> str | None:
    """Return the canonical field name for a CSV column, or None if unknown."""
    col_norm = col.strip().lower()
    for field, aliases in _FIELD_ALIASES.items():
        if col_norm in [a.lower() for a in aliases]:
            return field
    return None


def _suggest_mapping(columns: list[str]) -> list[ColumnMappingItem]:
    return [ColumnMappingItem(csv_column=c, field=_detect_field(c)) for c in columns]


async def _mx_valid(domain: str) -> bool:
    if domain in _mx_cache:
        return _mx_cache[domain]
    try:
        loop = asyncio.get_event_loop()
        records = await loop.run_in_executor(
            None,
            lambda: dns.resolver.resolve(domain, "MX", lifetime=5),
        )
        result = len(records) > 0
    except Exception:
        result = False
    _mx_cache[domain] = result
    return result


def _parse_file(content: bytes, filename: str) -> pd.DataFrame:
    if filename.lower().endswith(".xlsx") or filename.lower().endswith(".xls"):
        return pd.read_excel(io.BytesIO(content), dtype=str)
    # Default: CSV
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(content), dtype=str, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Cannot decode CSV file — unsupported encoding")


async def preview_import(file: UploadFile) -> ImportPreviewResponse:
    content = await file.read()
    df = _parse_file(content, file.filename or "upload.csv")
    df = df.fillna("")

    columns = list(df.columns)
    total_rows = len(df)
    preview_rows: list[dict[str, Any]] = df.head(10).to_dict(orient="records")

    return ImportPreviewResponse(
        rows=preview_rows,
        columns=columns,
        suggested_mapping=_suggest_mapping(columns),
        total_rows=total_rows,
    )


def _normalize_platform(val: str) -> str | None:
    v = val.strip().lower()
    return v if v in _PLATFORM_VALUES else None


async def confirm_import(
    file: UploadFile,
    mapping: list[ColumnMappingItem],
    overwrite_duplicates: bool,
    db: AsyncSession,
) -> ImportConfirmResponse:
    content = await file.read()
    df = _parse_file(content, file.filename or "upload.csv")
    df = df.fillna("")

    # Build column → field lookup (skip None)
    col_to_field: dict[str, str] = {
        m.csv_column: m.field
        for m in mapping
        if m.field is not None and m.csv_column in df.columns
    }

    if "email" not in col_to_field.values():
        raise ValueError("Mapping must include an 'email' column")

    imported = 0
    duplicates = 0
    invalid = 0
    errors: list[str] = []

    for idx, row in df.iterrows():
        # Map columns to fields
        data: dict[str, Any] = {}
        for csv_col, field in col_to_field.items():
            val = str(row.get(csv_col, "")).strip()
            data[field] = val

        email = data.get("email", "").lower().strip()

        # Validate email format
        if not email or not _EMAIL_RE.match(email):
            invalid += 1
            continue

        # MX record validation
        domain = email.split("@")[1]
        if not await _mx_valid(domain):
            invalid += 1
            errors.append(f"Row {idx}: {email} — MX validation failed")
            continue

        # Check for duplicates
        existing_result = await db.execute(
            select(Influencer).where(Influencer.email == email)
        )
        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            if not overwrite_duplicates:
                duplicates += 1
                continue
            # Overwrite: update fields
            if data.get("nickname"):
                existing.nickname = data["nickname"]
            if data.get("platform"):
                pf = _normalize_platform(data["platform"])
                if pf:
                    existing.platform = InfluencerPlatform(pf)
            if data.get("followers") and data["followers"].isdigit():
                existing.followers = int(data["followers"])
            if data.get("profile_url"):
                existing.profile_url = data["profile_url"]
            if data.get("industry"):
                existing.industry = data["industry"]
            await db.commit()
            imported += 1
        else:
            # Create new influencer
            platform_str = _normalize_platform(data.get("platform", ""))
            followers_val = data.get("followers", "")
            inf = Influencer(
                email=email,
                nickname=data.get("nickname") or None,
                platform=InfluencerPlatform(platform_str) if platform_str else None,
                followers=int(followers_val) if followers_val and followers_val.isdigit() else None,
                profile_url=data.get("profile_url") or None,
                industry=data.get("industry") or None,
            )
            db.add(inf)
            await db.commit()
            imported += 1

    return ImportConfirmResponse(
        imported=imported,
        duplicates=duplicates,
        invalid=invalid,
        total=len(df),
        errors=errors[:20],  # cap at 20 error messages
    )
