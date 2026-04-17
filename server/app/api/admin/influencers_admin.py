import asyncio
import uuid
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Optional

import dns.asyncresolver
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.email import Email
from app.models.influencer import Influencer
from app.models.influencer_tag import InfluencerTag
from app.models.scrape_task_influencer import ScrapeTaskInfluencer
from app.models.tag import Tag
from app.schemas.auth import TokenData

router = APIRouter(prefix="/influencers", tags=["admin-influencers"])

# In-memory task registry for batch MX verification
_verify_tasks: dict[str, dict[str, Any]] = {}


# ─── Schemas ─────────────────────────────────────────────────────────────────


class MergeRequest(BaseModel):
    primary_id: int
    secondary_ids: list[int]


class BatchVerifyRequest(BaseModel):
    influencer_ids: list[int] = []


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _check_mx(domain: str) -> bool:
    try:
        resolver = dns.asyncresolver.Resolver()
        resolver.lifetime = 5.0
        answers = await resolver.resolve(domain, "MX")
        return len(list(answers)) > 0
    except Exception:
        return False


async def _run_mx_verification(task_id: str, ids: list[int]) -> None:
    _verify_tasks[task_id]["status"] = "running"
    for inf_id in ids:
        ok = False
        try:
            async with AsyncSessionLocal() as db:
                inf = await db.get(Influencer, inf_id)
                if inf and "@" in inf.email:
                    domain = inf.email.split("@")[-1]
                    ok = await _check_mx(domain)
        except Exception:
            ok = False

        task = _verify_tasks[task_id]
        task["done"] += 1
        task["results"][str(inf_id)] = ok
        if ok:
            task["passed"] += 1
        else:
            task["failed"] += 1

    _verify_tasks[task_id]["status"] = "done"


def _inf_dict(
    inf: Influencer,
    email_count: int,
    tags: list[str],
    task_ids: list[int],
) -> dict:
    return {
        "id": inf.id,
        "nickname": inf.nickname,
        "email": inf.email,
        "platform": inf.platform.value if inf.platform else None,
        "profile_url": inf.profile_url,
        "followers": inf.followers,
        "industry": inf.industry,
        "status": inf.status.value,
        "priority": inf.priority.value,
        "follow_up_count": inf.follow_up_count,
        "created_at": inf.created_at.isoformat(),
        "creator": None,  # model has no created_by column; MVP returns null
        "email_count": email_count,
        "tags": tags,
        "task_ids": task_ids,
    }


async def _fetch_related(db, ids: list[int]) -> tuple[dict, dict, dict]:
    if not ids:
        return {}, {}, {}

    email_counts = dict(
        (
            await db.execute(
                select(Email.influencer_id, func.count(Email.id))
                .where(Email.influencer_id.in_(ids))
                .group_by(Email.influencer_id)
            )
        ).all()
    )

    tag_rows = (
        await db.execute(
            select(InfluencerTag.influencer_id, Tag.name)
            .join(Tag, InfluencerTag.tag_id == Tag.id)
            .where(InfluencerTag.influencer_id.in_(ids))
        )
    ).all()
    tags_map: dict[int, list[str]] = {}
    for inf_id, tag_name in tag_rows:
        tags_map.setdefault(inf_id, []).append(tag_name)

    task_rows = (
        await db.execute(
            select(
                ScrapeTaskInfluencer.influencer_id,
                ScrapeTaskInfluencer.scrape_task_id,
            ).where(ScrapeTaskInfluencer.influencer_id.in_(ids))
        )
    ).all()
    task_ids_map: dict[int, list[int]] = {}
    for inf_id, task_id in task_rows:
        task_ids_map.setdefault(inf_id, []).append(task_id)

    return email_counts, tags_map, task_ids_map


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.get("")
async def list_influencers_admin(
    page: int = 1,
    page_size: int = 50,
    platform: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        base_q = select(Influencer)
        if platform:
            base_q = base_q.where(Influencer.platform == platform)
        if status:
            base_q = base_q.where(Influencer.status == status)
        if search:
            base_q = base_q.where(
                Influencer.nickname.ilike(f"%{search}%")
                | Influencer.email.ilike(f"%{search}%")
            )

        total = (
            await db.execute(select(func.count()).select_from(base_q.subquery()))
        ).scalar_one()
        influencers = (
            await db.execute(
                base_q.order_by(Influencer.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).scalars().all()

        if not influencers:
            return {"total": total, "page": page, "page_size": page_size, "items": []}

        ids = [inf.id for inf in influencers]
        email_counts, tags_map, task_ids_map = await _fetch_related(db, ids)

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            _inf_dict(
                inf,
                email_counts.get(inf.id, 0),
                tags_map.get(inf.id, []),
                task_ids_map.get(inf.id, []),
            )
            for inf in influencers
        ],
    }


@router.get("/quality-report")
async def get_quality_report(
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        total = (
            await db.execute(select(func.count(Influencer.id)))
        ).scalar_one() or 0

        empty_email = (
            await db.execute(
                select(func.count(Influencer.id)).where(Influencer.email == "")
            )
        ).scalar_one() or 0

        invalid_email = (
            await db.execute(
                select(func.count(Influencer.id)).where(
                    ~Influencer.email.like("%@%.%")
                )
            )
        ).scalar_one() or 0

        missing_followers = (
            await db.execute(
                select(func.count(Influencer.id)).where(
                    Influencer.followers.is_(None)
                )
            )
        ).scalar_one() or 0

        missing_bio = (
            await db.execute(
                select(func.count(Influencer.id)).where(
                    (Influencer.bio.is_(None)) | (Influencer.bio == "")
                )
            )
        ).scalar_one() or 0

    def pct(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    return {
        "total": total,
        "empty_email": {"count": empty_email, "pct": pct(empty_email)},
        "invalid_email": {"count": invalid_email, "pct": pct(invalid_email)},
        "missing_followers": {"count": missing_followers, "pct": pct(missing_followers)},
        "missing_bio": {"count": missing_bio, "pct": pct(missing_bio)},
    }


@router.get("/duplicates")
async def get_duplicates(
    current_user: TokenData = Depends(require_admin),
) -> list:
    async with AsyncSessionLocal() as db:
        influencers = (await db.execute(select(Influencer))).scalars().all()

        if not influencers:
            return []

        ids = [inf.id for inf in influencers]
        email_counts, tags_map, task_ids_map = await _fetch_related(db, ids)

    # Union-Find for grouping (both email exact and name similarity paths)
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    linked: set[int] = set()
    email_linked: set[int] = set()  # IDs grouped via email exact match

    # Path 1: Email exact match — group influencers sharing the same non-empty email
    email_map: dict[str, list[Influencer]] = {}
    for inf in influencers:
        if inf.email:
            email_map.setdefault(inf.email, []).append(inf)

    for group in email_map.values():
        if len(group) > 1:
            for other in group[1:]:
                union(group[0].id, other.id)
                email_linked.add(group[0].id)
                email_linked.add(other.id)
                linked.add(group[0].id)
                linked.add(other.id)

    # Path 2: Name + platform similarity > 0.9
    platform_map: dict[str, list[Influencer]] = {}
    for inf in influencers:
        if inf.nickname and inf.platform:
            platform_map.setdefault(inf.platform.value, []).append(inf)

    for platform_infs in platform_map.values():
        n = len(platform_infs)
        for i in range(n):
            for j in range(i + 1, n):
                a, b = platform_infs[i], platform_infs[j]
                sim = SequenceMatcher(
                    None, a.nickname.lower(), b.nickname.lower()
                ).ratio()
                if sim > 0.9:
                    union(a.id, b.id)
                    linked.add(a.id)
                    linked.add(b.id)

    inf_by_id = {inf.id: inf for inf in influencers}
    groups_by_root: dict[int, list[Influencer]] = defaultdict(list)
    for inf_id in linked:
        groups_by_root[find(inf_id)].append(inf_by_id[inf_id])

    return [
        {
            "type": (
                "email_exact"
                if any(inf.id in email_linked for inf in group_infs)
                else "name_similarity"
            ),
            "influencers": [
                _inf_dict(
                    g,
                    email_counts.get(g.id, 0),
                    tags_map.get(g.id, []),
                    task_ids_map.get(g.id, []),
                )
                for g in group_infs
            ],
        }
        for group_infs in groups_by_root.values()
        if len(group_infs) > 1
    ]


@router.post("/merge")
async def merge_influencers(
    body: MergeRequest,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    if body.primary_id in body.secondary_ids:
        raise HTTPException(
            status_code=422, detail="primary_id must not be in secondary_ids"
        )
    if not body.secondary_ids:
        raise HTTPException(status_code=422, detail="secondary_ids must not be empty")

    async with AsyncSessionLocal() as db:
        if not await db.get(Influencer, body.primary_id):
            raise HTTPException(status_code=404, detail="Primary influencer not found")
        for sec_id in body.secondary_ids:
            if not await db.get(Influencer, sec_id):
                raise HTTPException(
                    status_code=404, detail=f"Secondary influencer {sec_id} not found"
                )

        # Migrate emails
        await db.execute(
            update(Email)
            .where(Email.influencer_id.in_(body.secondary_ids))
            .values(influencer_id=body.primary_id)
        )

        # Migrate tags (unique constraint: influencer_id + tag_id)
        primary_tags = set(
            (
                await db.execute(
                    select(InfluencerTag.tag_id).where(
                        InfluencerTag.influencer_id == body.primary_id
                    )
                )
            ).scalars().all()
        )
        for sec_id in body.secondary_ids:
            sec_tag_ids = (
                await db.execute(
                    select(InfluencerTag.tag_id).where(
                        InfluencerTag.influencer_id == sec_id
                    )
                )
            ).scalars().all()
            to_move = [t for t in sec_tag_ids if t not in primary_tags]
            if to_move:
                await db.execute(
                    update(InfluencerTag)
                    .where(
                        InfluencerTag.influencer_id == sec_id,
                        InfluencerTag.tag_id.in_(to_move),
                    )
                    .values(influencer_id=body.primary_id)
                )
                primary_tags.update(to_move)
            await db.execute(
                delete(InfluencerTag).where(InfluencerTag.influencer_id == sec_id)
            )

        # Migrate scrape_task_influencers (composite PK)
        primary_task_ids = set(
            (
                await db.execute(
                    select(ScrapeTaskInfluencer.scrape_task_id).where(
                        ScrapeTaskInfluencer.influencer_id == body.primary_id
                    )
                )
            ).scalars().all()
        )
        for sec_id in body.secondary_ids:
            sec_task_ids = (
                await db.execute(
                    select(ScrapeTaskInfluencer.scrape_task_id).where(
                        ScrapeTaskInfluencer.influencer_id == sec_id
                    )
                )
            ).scalars().all()
            to_move = [t for t in sec_task_ids if t not in primary_task_ids]
            if to_move:
                await db.execute(
                    update(ScrapeTaskInfluencer)
                    .where(
                        ScrapeTaskInfluencer.influencer_id == sec_id,
                        ScrapeTaskInfluencer.scrape_task_id.in_(to_move),
                    )
                    .values(influencer_id=body.primary_id)
                )
                primary_task_ids.update(to_move)
            await db.execute(
                delete(ScrapeTaskInfluencer).where(
                    ScrapeTaskInfluencer.influencer_id == sec_id
                )
            )

        # Delete secondary influencers
        await db.execute(
            delete(Influencer).where(Influencer.id.in_(body.secondary_ids))
        )
        await db.commit()

    return {"merged": len(body.secondary_ids), "primary_id": body.primary_id}


@router.post("/batch-verify-email")
async def start_batch_verify(
    body: BatchVerifyRequest,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    async with AsyncSessionLocal() as db:
        if body.influencer_ids:
            ids = list(body.influencer_ids)
        else:
            ids = list(
                (await db.execute(select(Influencer.id))).scalars().all()
            )

    task_id = str(uuid.uuid4())
    _verify_tasks[task_id] = {
        "status": "pending",
        "total": len(ids),
        "done": 0,
        "passed": 0,
        "failed": 0,
        "results": {},
    }
    asyncio.create_task(_run_mx_verification(task_id, ids))

    return {"task_id": task_id, "total": len(ids)}


@router.get("/batch-verify-email/{task_id}")
async def get_batch_verify_status(
    task_id: str,
    current_user: TokenData = Depends(require_admin),
) -> dict:
    task = _verify_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
