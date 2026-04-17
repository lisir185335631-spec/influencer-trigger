"""
Unified LLM client — all LLM calls in server/app must go through this module.
Automatically records token usage via usage_service.
"""
import asyncio
import logging
from typing import Any, Optional

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


async def chat(
    model: str,
    messages: list[dict[str, Any]],
    user_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """
    Unified async chat completion. Returns the content string.
    Automatically records token usage in background.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        **kwargs,
    )
    usage = response.usage
    if usage:
        try:
            from app.services.admin.usage_service import record_llm_usage
            asyncio.create_task(
                record_llm_usage(
                    model=model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    user_id=user_id,
                )
            )
        except Exception as exc:
            logger.debug("Usage tracking skipped: %s", exc)
    return response.choices[0].message.content or ""


async def embed(
    input_text: str,
    model: str = "text-embedding-3-small",
    user_id: Optional[str] = None,
) -> list[float]:
    """Unified async embedding call."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.embeddings.create(model=model, input=input_text)
    return response.data[0].embedding
