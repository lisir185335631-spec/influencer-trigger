import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select

from app.api.admin.deps import require_admin
from app.database import AsyncSessionLocal
from app.models.usage_metric import UsageMetric
from app.models.usage_budget import UsageBudget
from app.schemas.auth import TokenData

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/usage", tags=["admin-usage"])


def _period_start(period: str) -> date:
    today = date.today()
    if period == "day":
        return today
    elif period == "week":
        return today - timedelta(days=6)
    else:  # month
        return today.replace(day=1)


@router.get("/summary")
async def get_usage_summary(
    period: str = "month",
    _: TokenData = Depends(require_admin),
) -> dict:
    since = _period_start(period)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    UsageMetric.metric_type,
                    func.sum(UsageMetric.value).label("total_value"),
                    func.sum(UsageMetric.cost_usd).label("total_cost"),
                ).where(UsageMetric.metric_date >= since)
                .group_by(UsageMetric.metric_type)
            )
        ).all()

        summary: dict = {
            "total_cost_usd": 0.0,
            "llm_tokens": 0,
            "emails_sent": 0,
            "scrape_runs": 0,
            "storage_mb": 0.0,
        }
        for row in rows:
            mtype, val, cost = row.metric_type, row.total_value or 0, row.total_cost or 0
            summary["total_cost_usd"] += cost
            if mtype == "llm_token":
                summary["llm_tokens"] = int(val)
            elif mtype == "email_sent":
                summary["emails_sent"] = int(val)
            elif mtype == "scrape_run":
                summary["scrape_runs"] = int(val)
            elif mtype == "storage_mb":
                summary["storage_mb"] = float(val)
        summary["total_cost_usd"] = round(summary["total_cost_usd"], 4)
        return summary


@router.get("/trend")
async def get_usage_trend(
    metric: str = "llm_token",
    period: str = "30d",
    _: TokenData = Depends(require_admin),
) -> dict:
    days = int(period.rstrip("d")) if period.endswith("d") else 30
    since = date.today() - timedelta(days=days - 1)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    UsageMetric.metric_date,
                    func.sum(UsageMetric.value).label("value"),
                    func.sum(UsageMetric.cost_usd).label("cost"),
                ).where(
                    UsageMetric.metric_type == metric,
                    UsageMetric.metric_date >= since,
                ).group_by(UsageMetric.metric_date)
                .order_by(UsageMetric.metric_date)
            )
        ).all()
    return {
        "metric": metric,
        "data": [
            {
                "date": str(r.metric_date),
                "value": r.value or 0,
                "cost_usd": round(r.cost or 0, 4),
            }
            for r in rows
        ],
    }


@router.get("/breakdown")
async def get_usage_breakdown(
    metric: str = "llm_token",
    dimension: str = "model",
    _: TokenData = Depends(require_admin),
) -> dict:
    since = date.today().replace(day=1)
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    UsageMetric.sub_key,
                    func.sum(UsageMetric.value).label("value"),
                    func.sum(UsageMetric.cost_usd).label("cost"),
                ).where(
                    UsageMetric.metric_type == metric,
                    UsageMetric.metric_date >= since,
                ).group_by(UsageMetric.sub_key)
                .order_by(func.sum(UsageMetric.cost_usd).desc())
                .limit(20)
            )
        ).all()
    return {
        "metric": metric,
        "dimension": dimension,
        "data": [
            {
                "key": r.sub_key or "unknown",
                "value": r.value or 0,
                "cost_usd": round(r.cost or 0, 4),
            }
            for r in rows
        ],
    }


@router.get("/alerts")
async def get_usage_alerts(_: TokenData = Depends(require_admin)) -> dict:
    today = date.today()
    month_str = today.strftime("%Y-%m")
    month_start = today.replace(day=1)
    async with AsyncSessionLocal() as db:
        budget_row = (
            await db.execute(
                select(UsageBudget).where(UsageBudget.month == month_str)
            )
        ).scalar_one_or_none()

        month_cost = (
            await db.execute(
                select(func.sum(UsageMetric.cost_usd)).where(
                    UsageMetric.metric_date >= month_start,
                )
            )
        ).scalar() or 0.0

        today_cost = (
            await db.execute(
                select(func.sum(UsageMetric.cost_usd)).where(
                    UsageMetric.metric_date == today,
                )
            )
        ).scalar() or 0.0

    alerts = []
    if budget_row:
        threshold = budget_row.budget_usd * budget_row.alert_threshold_pct / 100
        pct_used = (month_cost / budget_row.budget_usd * 100) if budget_row.budget_usd else 0
        if month_cost >= threshold:
            alerts.append({
                "type": "monthly_budget",
                "message": (
                    f"Month cost ${month_cost:.2f} exceeds {budget_row.alert_threshold_pct}% "
                    f"of ${budget_row.budget_usd:.2f} budget ({pct_used:.1f}% used)"
                ),
                "severity": "warning" if pct_used < 100 else "critical",
            })

    return {
        "month": month_str,
        "month_cost_usd": round(month_cost, 4),
        "today_cost_usd": round(today_cost, 4),
        "budget": {
            "budget_usd": budget_row.budget_usd if budget_row else None,
            "alert_threshold_pct": budget_row.alert_threshold_pct if budget_row else 80,
        } if budget_row else None,
        "alerts": alerts,
    }


class BudgetIn(BaseModel):
    month: str  # YYYY-MM
    budget_usd: float
    alert_threshold_pct: float = 80.0


@router.post("/budget")
async def set_budget(
    body: BudgetIn,
    _: TokenData = Depends(require_admin),
) -> dict:
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert
    async with AsyncSessionLocal() as db:
        stmt = sqlite_insert(UsageBudget).values(
            month=body.month,
            budget_usd=body.budget_usd,
            alert_threshold_pct=body.alert_threshold_pct,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["month"],
            set_={
                "budget_usd": body.budget_usd,
                "alert_threshold_pct": body.alert_threshold_pct,
            },
        )
        await db.execute(stmt)
        await db.commit()
    return {"ok": True, "month": body.month}
