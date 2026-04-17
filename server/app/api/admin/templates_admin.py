from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.compliance_keywords import ComplianceKeyword
from app.models.email import Email, EmailStatus
from app.models.template import Template
from app.models.user import User
from app.schemas.auth import TokenData

router = APIRouter(prefix="/templates", tags=["admin-templates"])

_SUCCESS_STATUSES = {
    EmailStatus.sent, EmailStatus.delivered, EmailStatus.opened,
    EmailStatus.clicked, EmailStatus.replied,
}


async def _template_stats(db, template_id: int) -> tuple[int, float]:
    """Return (usage_count, send_success_rate) for a template."""
    total = (await db.execute(
        select(func.count()).where(Email.template_id == template_id)
    )).scalar() or 0
    if total == 0:
        return 0, 0.0
    sent = (await db.execute(
        select(func.count()).where(
            Email.template_id == template_id,
            Email.status.in_([s.value for s in _SUCCESS_STATUSES]),
        )
    )).scalar() or 0
    return total, round(sent / total * 100, 1)


# ─── Template Admin Endpoints ──────────────────────────────────────────────────

@router.get("")
async def list_admin_templates(_: TokenData = Depends(require_admin)) -> dict:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Template, User.username)
            .outerjoin(User, User.id == Template.created_by)
            .order_by(Template.created_at.desc())
        )).all()

        items = []
        for tmpl, username in rows:
            usage, success_rate = await _template_stats(db, tmpl.id)
            items.append({
                "id": tmpl.id,
                "name": tmpl.name,
                "subject": tmpl.subject,
                "body_html": tmpl.body_html,
                "industry": tmpl.industry,
                "style": tmpl.style,
                "language": tmpl.language,
                "is_published": tmpl.is_published,
                "compliance_flags": tmpl.compliance_flags,
                "created_by": tmpl.created_by,
                "creator_username": username,
                "usage_count": usage,
                "send_success_rate": success_rate,
                "created_at": tmpl.created_at.isoformat(),
            })
        return {"total": len(items), "items": items}


@router.post("/{template_id}/publish")
async def publish_template(
    template_id: int,
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        tmpl = await db.get(Template, template_id)
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")
        tmpl.is_published = True
        await db.commit()
        return {"ok": True, "id": template_id, "is_published": True}


@router.post("/{template_id}/unpublish")
async def unpublish_template(
    template_id: int,
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        tmpl = await db.get(Template, template_id)
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")
        tmpl.is_published = False
        await db.commit()
        return {"ok": True, "id": template_id, "is_published": False}


@router.post("/{template_id}/compliance-scan")
async def compliance_scan(
    template_id: int,
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        tmpl = await db.get(Template, template_id)
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")

        keywords = (await db.execute(select(ComplianceKeyword))).scalars().all()
        content = f"{tmpl.name} {tmpl.subject} {tmpl.body_html}".lower()
        hits = [kw.keyword for kw in keywords if kw.keyword.lower() in content]
        tmpl.compliance_flags = ",".join(hits)
        await db.commit()
        return {"ok": True, "id": template_id, "compliance_flags": tmpl.compliance_flags, "hits": hits}


@router.get("/ranking")
async def templates_ranking(_: TokenData = Depends(require_admin)) -> dict:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(
                Template.id,
                Template.name,
                Template.industry,
                Template.is_published,
                func.count(Email.id).label("usage_count"),
            )
            .outerjoin(Email, Email.template_id == Template.id)
            .group_by(Template.id)
            .order_by(func.count(Email.id).desc())
            .limit(20)
        )).all()

        items = []
        for row in rows:
            items.append({
                "id": row.id,
                "name": row.name,
                "industry": row.industry,
                "is_published": row.is_published,
                "usage_count": row.usage_count,
            })
        return {"items": items}


# ─── Compliance Keywords CRUD ──────────────────────────────────────────────────

class KeywordCreate(BaseModel):
    keyword: str
    category: str
    severity: str


@router.get("/keywords")
async def list_keywords(_: TokenData = Depends(require_admin)) -> dict:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(ComplianceKeyword).order_by(ComplianceKeyword.created_at.desc())
        )).scalars().all()
        items = [
            {
                "id": kw.id,
                "keyword": kw.keyword,
                "category": kw.category,
                "severity": kw.severity,
                "created_at": kw.created_at.isoformat(),
            }
            for kw in rows
        ]
        return {"total": len(items), "items": items}


@router.post("/keywords")
async def create_keyword(
    body: KeywordCreate,
    _: TokenData = Depends(require_admin),
) -> dict:
    if body.category not in ("政治", "暴力", "色情", "其他"):
        raise HTTPException(status_code=400, detail="Invalid category")
    if body.severity not in ("low", "medium", "high"):
        raise HTTPException(status_code=400, detail="Invalid severity")

    async with AsyncSessionLocal() as db:
        existing = (await db.execute(
            select(ComplianceKeyword).where(ComplianceKeyword.keyword == body.keyword)
        )).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="Keyword already exists")

        kw = ComplianceKeyword(keyword=body.keyword, category=body.category, severity=body.severity)
        db.add(kw)
        await db.commit()
        await db.refresh(kw)
        return {"id": kw.id, "keyword": kw.keyword, "category": kw.category, "severity": kw.severity}


@router.delete("/keywords/{keyword_id}")
async def delete_keyword(
    keyword_id: int,
    _: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        kw = await db.get(ComplianceKeyword, keyword_id)
        if not kw:
            raise HTTPException(status_code=404, detail="Keyword not found")
        await db.delete(kw)
        await db.commit()
        return {"ok": True, "id": keyword_id}
