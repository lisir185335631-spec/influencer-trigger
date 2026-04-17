"""
Holiday Agent — Generates personalized holiday greeting emails using GPT-4o.

Falls back to static templates if OpenAI is unavailable.
"""
import logging
from typing import Optional

from app.config import get_settings
from app.models.holiday import Holiday
from app.models.influencer import Influencer

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are writing a warm, brief holiday greeting email for an influencer marketing brand.
Write a genuine, non-salesy holiday greeting (max 80 words) that:
1. Wishes the influencer well on the holiday
2. Subtly acknowledges their work in their industry
3. Keeps a friendly, personal tone — feels human, not automated
4. Does NOT include any sales pitch or collaboration request

Return ONLY valid JSON:
{"subject": "email subject line here", "body_html": "<p>email body in HTML (only p tags)</p>"}"""


async def generate_holiday_greeting(
    influencer: Influencer,
    holiday: Holiday,
) -> Optional[tuple[str, str]]:
    """
    Generate a personalized holiday greeting (subject, body_html) via GPT-4o.
    Returns None if OpenAI is not configured or the call fails.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set; using static holiday greeting template")
        return None

    name = influencer.nickname or influencer.email.split("@")[0]
    platform = influencer.platform.value if influencer.platform else "social media"
    industry = influencer.industry or "content creation"

    user_prompt = (
        f"Influencer details:\n"
        f"  Name: {name}\n"
        f"  Platform: {platform}\n"
        f"  Industry: {industry}\n\n"
        f"Holiday: {holiday.name}\n\n"
        f"Write a warm, personal holiday greeting for this influencer."
    )

    try:
        import json
        from app.tools.llm_client import chat as llm_chat

        raw = await llm_chat(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.9,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        raw = raw or "{}"
        data = json.loads(raw)
        subject = data.get("subject", "").strip()
        body_html = data.get("body_html", "").strip()
        if not subject or not body_html:
            raise ValueError("Missing subject or body_html in GPT response")
        return subject, body_html
    except Exception as exc:
        logger.error("Holiday Agent GPT call failed: %s", exc)
        return None


def _static_greeting(influencer: Influencer, holiday: Holiday) -> tuple[str, str]:
    """Static fallback greeting when OpenAI is unavailable."""
    name = influencer.nickname or influencer.email.split("@")[0]
    platform = influencer.platform.value if influencer.platform else "social media"

    greetings = {
        "Christmas": (
            f"Wishing you a Merry Christmas, {name}!",
            f"<p>Hi {name},</p>"
            f"<p>Wishing you and your loved ones a very Merry Christmas! "
            f"Thank you for the amazing content you share on {platform} — "
            f"it's been a pleasure following your journey.</p>"
            f"<p>Here's to a wonderful holiday season! 🎄</p>"
            f"<p>Warm regards</p>",
        ),
        "New Year's Day": (
            f"Happy New Year, {name}! 🎆",
            f"<p>Hi {name},</p>"
            f"<p>Wishing you a fantastic New Year filled with exciting opportunities! "
            f"Looking forward to seeing what you create on {platform} in the year ahead.</p>"
            f"<p>Happy New Year! 🥂</p>"
            f"<p>Best wishes</p>",
        ),
        "Valentine's Day": (
            f"Happy Valentine's Day, {name}! 💝",
            f"<p>Hi {name},</p>"
            f"<p>Happy Valentine's Day! We appreciate the love and creativity you pour into your {platform} content.</p>"
            f"<p>Hope your day is filled with joy! ❤️</p>"
            f"<p>Best wishes</p>",
        ),
        "Easter": (
            f"Happy Easter, {name}! 🐣",
            f"<p>Hi {name},</p>"
            f"<p>Wishing you a joyful Easter! Hope the season brings you fresh inspiration "
            f"for your wonderful {platform} content.</p>"
            f"<p>Happy Easter! 🌸</p>"
            f"<p>Best wishes</p>",
        ),
        "Halloween": (
            f"Happy Halloween, {name}! 🎃",
            f"<p>Hi {name},</p>"
            f"<p>Happy Halloween! Hope you're having a spooktacular time. "
            f"Your creative energy on {platform} never fails to impress!</p>"
            f"<p>Have a frightfully fun day! 🎃</p>"
            f"<p>Best wishes</p>",
        ),
        "Thanksgiving": (
            f"Happy Thanksgiving, {name}! 🦃",
            f"<p>Hi {name},</p>"
            f"<p>Happy Thanksgiving! We're grateful for creators like you who bring "
            f"so much value and creativity to {platform}.</p>"
            f"<p>Hope you enjoy a wonderful day with family and friends! 🍂</p>"
            f"<p>With gratitude</p>",
        ),
    }

    if holiday.name in greetings:
        return greetings[holiday.name]

    # Generic fallback
    subject = f"Happy {holiday.name}, {name}!"
    body_html = (
        f"<p>Hi {name},</p>"
        f"<p>Wishing you a wonderful {holiday.name}! "
        f"Thank you for the great content you create on {platform}.</p>"
        f"<p>Hope you have a fantastic day! 🎉</p>"
        f"<p>Best wishes</p>"
    )
    return subject, body_html


async def get_holiday_greeting(
    influencer: Influencer,
    holiday: Holiday,
) -> tuple[str, str]:
    """
    Return (subject, body_html) for a holiday greeting.
    Tries GPT-4o first; falls back to static templates.
    """
    result = await generate_holiday_greeting(influencer, holiday)
    if result:
        return result
    return _static_greeting(influencer, holiday)
