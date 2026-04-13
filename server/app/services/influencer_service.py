import csv
import io
from typing import Optional
from sqlalchemy import select, delete, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.influencer import Influencer, InfluencerStatus, InfluencerPriority
from app.models.tag import Tag
from app.models.influencer_tag import InfluencerTag
from app.models.note import Note
from app.models.collaboration import Collaboration
from app.models.email import Email
from app.schemas.influencer import (
    BatchUpdateRequest,
    InfluencerUpdate,
    TagCreate,
    NoteCreate,
    TagOut,
    NoteOut,
    CollaborationOut,
    EmailTimelineItem,
    InfluencerDetail,
    InfluencerListItem,
)


# ── Influencer list ──────────────────────────────────────────────────────────

async def list_influencers(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    status: Optional[str] = None,
    platform: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    tag_ids: Optional[list[int]] = None,
    followers_min: Optional[int] = None,
    followers_max: Optional[int] = None,
    industry: Optional[str] = None,
    reply_intent: Optional[str] = None,
) -> tuple[list[InfluencerListItem], int]:
    query = select(Influencer)

    if status:
        query = query.where(Influencer.status == status)
    if platform:
        query = query.where(Influencer.platform == platform)
    if priority:
        query = query.where(Influencer.priority == priority)
    if search:
        like = f"%{search}%"
        query = query.where(
            (Influencer.email.ilike(like)) | (Influencer.nickname.ilike(like))
        )
    if industry:
        query = query.where(Influencer.industry.ilike(f"%{industry}%"))
    if reply_intent:
        query = query.where(Influencer.reply_intent == reply_intent)
    if followers_min is not None:
        query = query.where(Influencer.followers >= followers_min)
    if followers_max is not None:
        query = query.where(Influencer.followers <= followers_max)
    if tag_ids:
        # Influencer must have ALL specified tags (AND logic per tag)
        for tid in tag_ids:
            sub = select(InfluencerTag.influencer_id).where(InfluencerTag.tag_id == tid)
            query = query.where(Influencer.id.in_(sub))

    count_q = select(func.count()).select_from(query.subquery())
    total: int = (await db.execute(count_q)).scalar_one()

    query = query.order_by(Influencer.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = list((await db.execute(query)).scalars().all())

    items: list[InfluencerListItem] = []
    for inf in rows:
        tags = await _get_tags_for_influencer(db, inf.id)
        items.append(
            InfluencerListItem(
                id=inf.id,
                nickname=inf.nickname,
                email=inf.email,
                platform=inf.platform.value if inf.platform else None,
                followers=inf.followers,
                industry=inf.industry,
                status=inf.status.value,
                priority=inf.priority.value,
                reply_intent=inf.reply_intent.value if inf.reply_intent else None,
                follow_up_count=inf.follow_up_count,
                last_email_sent_at=inf.last_email_sent_at,
                created_at=inf.created_at,
                tags=tags,
            )
        )
    return items, total


# ── Influencer detail ────────────────────────────────────────────────────────

async def get_influencer_detail(db: AsyncSession, influencer_id: int) -> Optional[InfluencerDetail]:
    inf = await db.get(Influencer, influencer_id)
    if not inf:
        return None

    tags = await _get_tags_for_influencer(db, influencer_id)
    notes = await _get_notes(db, influencer_id)
    collaborations = await _get_collaborations(db, influencer_id)
    emails = await _get_emails(db, influencer_id)

    return InfluencerDetail(
        id=inf.id,
        nickname=inf.nickname,
        email=inf.email,
        platform=inf.platform.value if inf.platform else None,
        profile_url=inf.profile_url,
        followers=inf.followers,
        industry=inf.industry,
        bio=inf.bio,
        status=inf.status.value,
        priority=inf.priority.value,
        reply_intent=inf.reply_intent.value if inf.reply_intent else None,
        follow_up_count=inf.follow_up_count,
        last_email_sent_at=inf.last_email_sent_at,
        created_at=inf.created_at,
        updated_at=inf.updated_at,
        tags=tags,
        notes=notes,
        collaborations=collaborations,
        emails=emails,
    )


async def update_influencer(
    db: AsyncSession,
    influencer_id: int,
    data: InfluencerUpdate,
) -> Optional[Influencer]:
    inf = await db.get(Influencer, influencer_id)
    if not inf:
        return None

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "status" and value:
            setattr(inf, field, InfluencerStatus(value))
        elif field == "priority" and value:
            setattr(inf, field, InfluencerPriority(value))
        else:
            setattr(inf, field, value)

    await db.commit()
    await db.refresh(inf)
    return inf


# ── Email timeline ───────────────────────────────────────────────────────────

async def get_influencer_emails(db: AsyncSession, influencer_id: int) -> list[EmailTimelineItem]:
    return await _get_emails(db, influencer_id)


async def _get_emails(db: AsyncSession, influencer_id: int) -> list[EmailTimelineItem]:
    result = await db.execute(
        select(Email)
        .where(Email.influencer_id == influencer_id)
        .order_by(Email.created_at.desc())
    )
    emails = result.scalars().all()
    return [
        EmailTimelineItem(
            id=e.id,
            email_type=e.email_type.value,
            subject=e.subject,
            status=e.status.value,
            reply_content=e.reply_content,
            reply_from=e.reply_from,
            sent_at=e.sent_at,
            delivered_at=e.delivered_at,
            opened_at=e.opened_at,
            replied_at=e.replied_at,
            bounced_at=e.bounced_at,
            created_at=e.created_at,
        )
        for e in emails
    ]


# ── Notes ────────────────────────────────────────────────────────────────────

async def add_note(
    db: AsyncSession,
    influencer_id: int,
    data: NoteCreate,
    user_id: Optional[int] = None,
) -> NoteOut:
    note = Note(
        influencer_id=influencer_id,
        content=data.content,
        created_by=user_id,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return NoteOut.model_validate(note)


async def _get_notes(db: AsyncSession, influencer_id: int) -> list[NoteOut]:
    result = await db.execute(
        select(Note)
        .where(Note.influencer_id == influencer_id)
        .order_by(Note.created_at.desc())
    )
    return [NoteOut.model_validate(n) for n in result.scalars().all()]


# ── Tags ─────────────────────────────────────────────────────────────────────

async def list_tags(db: AsyncSession) -> list[TagOut]:
    result = await db.execute(select(Tag).order_by(Tag.name))
    return [TagOut.model_validate(t) for t in result.scalars().all()]


async def create_tag(db: AsyncSession, data: TagCreate) -> TagOut:
    tag = Tag(name=data.name, color=data.color)
    db.add(tag)
    await db.commit()
    await db.refresh(tag)
    return TagOut.model_validate(tag)


async def delete_tag(db: AsyncSession, tag_id: int) -> bool:
    tag = await db.get(Tag, tag_id)
    if not tag:
        return False
    await db.delete(tag)
    await db.commit()
    return True


async def assign_tags(
    db: AsyncSession,
    influencer_id: int,
    tag_ids: list[int],
) -> list[TagOut]:
    # Remove existing associations
    await db.execute(
        delete(InfluencerTag).where(InfluencerTag.influencer_id == influencer_id)
    )
    # Add new ones
    for tag_id in tag_ids:
        db.add(InfluencerTag(influencer_id=influencer_id, tag_id=tag_id))
    await db.commit()
    return await _get_tags_for_influencer(db, influencer_id)


async def _get_tags_for_influencer(db: AsyncSession, influencer_id: int) -> list[TagOut]:
    result = await db.execute(
        select(Tag)
        .join(InfluencerTag, InfluencerTag.tag_id == Tag.id)
        .where(InfluencerTag.influencer_id == influencer_id)
        .order_by(Tag.name)
    )
    return [TagOut.model_validate(t) for t in result.scalars().all()]


# ── Collaborations ───────────────────────────────────────────────────────────

async def _get_collaborations(db: AsyncSession, influencer_id: int) -> list[CollaborationOut]:
    result = await db.execute(
        select(Collaboration)
        .where(Collaboration.influencer_id == influencer_id)
        .order_by(Collaboration.created_at.desc())
    )
    return [CollaborationOut.model_validate(c) for c in result.scalars().all()]


# ── Batch operations ─────────────────────────────────────────────────────────

async def batch_update_influencers(
    db: AsyncSession,
    data: BatchUpdateRequest,
) -> int:
    """Apply batch action to a list of influencer IDs. Returns count of affected rows."""
    if not data.influencer_ids:
        return 0

    rows = list(
        (
            await db.execute(
                select(Influencer).where(Influencer.id.in_(data.influencer_ids))
            )
        )
        .scalars()
        .all()
    )

    if data.action == "archive":
        for inf in rows:
            inf.status = InfluencerStatus.archived

    elif data.action == "assign_tags" and data.tag_ids:
        for inf in rows:
            # Fetch existing tag IDs for this influencer
            existing = set(
                (
                    await db.execute(
                        select(InfluencerTag.tag_id).where(
                            InfluencerTag.influencer_id == inf.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            for tid in data.tag_ids:
                if tid not in existing:
                    db.add(InfluencerTag(influencer_id=inf.id, tag_id=tid))

    await db.commit()
    return len(rows)


# ── CSV export ────────────────────────────────────────────────────────────────

async def export_influencers_csv(
    db: AsyncSession,
    status: Optional[str] = None,
    platform: Optional[str] = None,
    priority: Optional[str] = None,
    search: Optional[str] = None,
    tag_ids: Optional[list[int]] = None,
    followers_min: Optional[int] = None,
    followers_max: Optional[int] = None,
    industry: Optional[str] = None,
    reply_intent: Optional[str] = None,
) -> str:
    """Return a CSV string of all matching influencers (no pagination)."""
    items, _ = await list_influencers(
        db=db,
        page=1,
        page_size=100_000,
        status=status,
        platform=platform,
        priority=priority,
        search=search,
        tag_ids=tag_ids,
        followers_min=followers_min,
        followers_max=followers_max,
        industry=industry,
        reply_intent=reply_intent,
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "nickname", "email", "platform", "followers",
        "industry", "status", "priority", "reply_intent",
        "tags", "follow_up_count", "last_email_sent_at", "created_at",
    ])
    for inf in items:
        writer.writerow([
            inf.id,
            inf.nickname or "",
            inf.email,
            inf.platform or "",
            inf.followers if inf.followers is not None else "",
            inf.industry or "",
            inf.status,
            inf.priority,
            inf.reply_intent or "",
            "|".join(t.name for t in inf.tags),
            inf.follow_up_count,
            inf.last_email_sent_at.isoformat() if inf.last_email_sent_at else "",
            inf.created_at.isoformat(),
        ])
    return output.getvalue()
