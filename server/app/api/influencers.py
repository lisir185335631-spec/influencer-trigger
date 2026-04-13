from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
import io

from app.database import get_db
from app.deps import get_current_user
from app.schemas.auth import TokenData
from app.schemas.influencer import (
    AssignTagsRequest,
    BatchUpdateRequest,
    BatchUpdateResponse,
    ExportRequest,
    InfluencerDetail,
    InfluencerListResponse,
    InfluencerUpdate,
    NoteCreate,
    NoteOut,
    TagCreate,
    TagOut,
)
from app.services.influencer_service import (
    add_note,
    assign_tags,
    batch_update_influencers,
    create_tag,
    delete_tag,
    export_influencers_csv,
    get_influencer_detail,
    get_influencer_emails,
    list_influencers,
    list_tags,
    update_influencer,
)

router = APIRouter(tags=["influencers"])


# ── Influencer list ──────────────────────────────────────────────────────────

@router.get("/influencers", response_model=InfluencerListResponse)
async def list_influencers_endpoint(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    priority: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    tag_ids: List[int] = Query(default=[]),
    followers_min: Optional[int] = Query(None),
    followers_max: Optional[int] = Query(None),
    industry: Optional[str] = Query(None),
    reply_intent: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> InfluencerListResponse:
    items, total = await list_influencers(
        db, page, page_size, status, platform, priority, search,
        tag_ids or None, followers_min, followers_max, industry, reply_intent,
    )
    total_pages = max(1, (total + page_size - 1) // page_size)
    return InfluencerListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


# ── Batch operations ─────────────────────────────────────────────────────────

@router.patch("/influencers/batch", response_model=BatchUpdateResponse)
async def batch_update_influencers_endpoint(
    body: BatchUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> BatchUpdateResponse:
    if body.action not in ("archive", "assign_tags"):
        raise HTTPException(status_code=400, detail="action must be 'archive' or 'assign_tags'")
    if body.action == "assign_tags" and not body.tag_ids:
        raise HTTPException(status_code=400, detail="tag_ids required for assign_tags action")
    affected = await batch_update_influencers(db, body)
    return BatchUpdateResponse(affected=affected)


# ── CSV Export ────────────────────────────────────────────────────────────────

@router.post("/influencers/export")
async def export_influencers_endpoint(
    body: ExportRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> StreamingResponse:
    csv_content = await export_influencers_csv(
        db,
        status=body.status,
        platform=body.platform,
        priority=body.priority,
        search=body.search,
        tag_ids=body.tag_ids,
        followers_min=body.followers_min,
        followers_max=body.followers_max,
        industry=body.industry,
        reply_intent=body.reply_intent,
    )
    return StreamingResponse(
        io.StringIO(csv_content),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=influencers.csv"},
    )


# ── Influencer detail ────────────────────────────────────────────────────────

@router.get("/influencers/{influencer_id}", response_model=InfluencerDetail)
async def get_influencer_detail_endpoint(
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> InfluencerDetail:
    detail = await get_influencer_detail(db, influencer_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Influencer not found")
    return detail


@router.patch("/influencers/{influencer_id}", response_model=InfluencerDetail)
async def update_influencer_endpoint(
    influencer_id: int,
    body: InfluencerUpdate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> InfluencerDetail:
    inf = await update_influencer(db, influencer_id, body)
    if not inf:
        raise HTTPException(status_code=404, detail="Influencer not found")
    detail = await get_influencer_detail(db, influencer_id)
    return detail  # type: ignore[return-value]


# ── Email timeline ───────────────────────────────────────────────────────────

@router.get("/influencers/{influencer_id}/emails", response_model=list)
async def get_influencer_emails_endpoint(
    influencer_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> list:
    detail = await get_influencer_detail(db, influencer_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Influencer not found")
    return await get_influencer_emails(db, influencer_id)  # type: ignore[return-value]


# ── Notes ────────────────────────────────────────────────────────────────────

@router.post(
    "/influencers/{influencer_id}/notes",
    response_model=NoteOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_note_endpoint(
    influencer_id: int,
    body: NoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: TokenData = Depends(get_current_user),
) -> NoteOut:
    detail = await get_influencer_detail(db, influencer_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Influencer not found")
    user_id = int(current_user.sub) if current_user.sub else None
    return await add_note(db, influencer_id, body, user_id)


# ── Tags ─────────────────────────────────────────────────────────────────────

@router.get("/tags", response_model=list[TagOut])
async def list_tags_endpoint(
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> list[TagOut]:
    return await list_tags(db)


@router.post("/tags", response_model=TagOut, status_code=status.HTTP_201_CREATED)
async def create_tag_endpoint(
    body: TagCreate,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> TagOut:
    return await create_tag(db, body)


@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag_endpoint(
    tag_id: int,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> None:
    deleted = await delete_tag(db, tag_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Tag not found")


@router.post("/influencers/{influencer_id}/tags", response_model=list[TagOut])
async def assign_tags_endpoint(
    influencer_id: int,
    body: AssignTagsRequest,
    db: AsyncSession = Depends(get_db),
    _: TokenData = Depends(get_current_user),
) -> list[TagOut]:
    detail = await get_influencer_detail(db, influencer_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Influencer not found")
    return await assign_tags(db, influencer_id, body.tag_ids)
