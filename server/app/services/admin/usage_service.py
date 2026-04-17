import logging
from datetime import date
from typing import Optional

from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.database import AsyncSessionLocal
from app.models.usage_metric import UsageMetric

logger = logging.getLogger(__name__)

# LLM pricing per 1M tokens (USD)
_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 5.0, "output": 15.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.0, "output": 30.0},
    "gpt-4": {"input": 30.0, "output": 60.0},
    "gpt-3.5-turbo": {"input": 0.5, "output": 1.5},
}


def _calc_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = _PRICING.get(model, {"input": 5.0, "output": 15.0})
    return (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000


async def record_llm_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    user_id: Optional[str] = None,
) -> None:
    """UPSERT: atomically accumulate LLM token usage for today."""
    today = date.today()
    total_tokens = prompt_tokens + completion_tokens
    cost = _calc_cost(model, prompt_tokens, completion_tokens)
    try:
        async with AsyncSessionLocal() as db:
            stmt = sqlite_insert(UsageMetric).values(
                metric_date=today,
                metric_type="llm_token",
                sub_key=model,
                value=float(total_tokens),
                cost_usd=cost,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["metric_date", "metric_type", "sub_key"],
                set_={
                    "value": UsageMetric.value + float(total_tokens),
                    "cost_usd": UsageMetric.cost_usd + cost,
                },
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as exc:
        logger.warning("record_llm_usage failed: %s", exc)


async def record_email_sent(user_id: Optional[str], count: int = 1) -> None:
    """UPSERT: atomically accumulate email sent count for today."""
    today = date.today()
    sub = user_id or "system"
    try:
        async with AsyncSessionLocal() as db:
            stmt = sqlite_insert(UsageMetric).values(
                metric_date=today,
                metric_type="email_sent",
                sub_key=sub,
                value=float(count),
                cost_usd=None,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["metric_date", "metric_type", "sub_key"],
                set_={"value": UsageMetric.value + float(count)},
            )
            await db.execute(stmt)
            await db.commit()
    except Exception as exc:
        logger.warning("record_email_sent failed: %s", exc)
