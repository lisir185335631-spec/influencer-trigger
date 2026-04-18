"""
Unified LLM client — all LLM calls in server/app must go through this module.
Automatically records token usage via usage_service.

Uses httpx directly (not the openai SDK) because some OpenAI-compatible proxies
block the SDK's X-Stainless-* diagnostic headers. Sending raw httpx requests
with minimal headers works across all proxies we've tested.
"""
import asyncio
import logging
from typing import Any, Optional

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"


class LLMError(Exception):
    """Raised when the LLM proxy returns a non-2xx response or unexpected shape."""


def _base_url() -> str:
    settings = get_settings()
    url = settings.openai_base_url.rstrip("/") if settings.openai_base_url else _DEFAULT_BASE_URL
    return url


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }


async def chat(
    model: str,
    messages: list[dict[str, Any]],
    user_id: Optional[str] = None,
    agent_name: Optional[str] = None,
    **kwargs: Any,
) -> str:
    """
    Unified async chat completion. Returns the assistant content string.
    Automatically records token usage in background (best-effort, non-blocking).

    kwargs pass through to the API (temperature, max_tokens, response_format, etc).
    """
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    payload: dict[str, Any] = {"model": model, "messages": messages}
    payload.update(kwargs)

    url = f"{_base_url()}/chat/completions"

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=_headers(), json=payload)

    if resp.status_code >= 400:
        logger.warning("LLM chat failed: HTTP %d — %s", resp.status_code, resp.text[:500])
        raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected LLM response shape: {data}") from exc

    usage = data.get("usage") or {}
    if usage:
        try:
            from app.services.admin.usage_service import record_llm_usage
            asyncio.create_task(
                record_llm_usage(
                    model=model,
                    prompt_tokens=usage.get("prompt_tokens", 0),
                    completion_tokens=usage.get("completion_tokens", 0),
                    user_id=user_id,
                )
            )
        except Exception as exc:
            logger.debug("Usage tracking skipped: %s", exc)

    return content


async def embed(
    input_text: str,
    model: str = "text-embedding-3-small",
    user_id: Optional[str] = None,
) -> list[float]:
    """Unified async embedding call."""
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    url = f"{_base_url()}/embeddings"
    payload = {"model": model, "input": input_text}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=_headers(), json=payload)

    if resp.status_code >= 400:
        logger.warning("LLM embed failed: HTTP %d — %s", resp.status_code, resp.text[:500])
        raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    try:
        return data["data"][0]["embedding"]
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMError(f"Unexpected embedding response shape: {data}") from exc
