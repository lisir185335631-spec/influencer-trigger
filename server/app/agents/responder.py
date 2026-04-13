"""
Responder Agent — Generates differentiated follow-up email content using GPT-4o.

Each follow-up uses a different angle based on follow_up_count so the
influencer never receives the same pitch twice.
"""
import logging
from typing import Optional

from app.config import get_settings
from app.models.influencer import Influencer

logger = logging.getLogger(__name__)

# Angle descriptions indexed by follow_up_count (0 = first follow-up)
_ANGLES = [
    "gentle reminder — you sent them an initial outreach and haven't heard back; keep it brief and friendly",
    "social proof — mention a success story or result from a similar collaboration to spark interest",
    "value proposition — lead with a clear, specific benefit the influencer would get from the collaboration",
    "FOMO angle — mention limited spots or a campaign launch timeline to create a sense of urgency",
    "personal touch — reference something specific about their content style or a recent post they made",
    "final outreach — let them know this is your last attempt; be respectful and leave the door open",
]

_SYSTEM_PROMPT = """You are an expert influencer outreach specialist writing follow-up emails for a brand collaboration campaign.
Write a short, genuine, personalized follow-up email (max 120 words) that:
1. Does NOT repeat the exact same pitch as a standard initial email
2. Feels human, warm, and direct — not salesy
3. Respects the influencer's time
4. Has a clear, concise subject line

Return ONLY valid JSON:
{
  "subject": "email subject line here",
  "body_html": "<p>email body in HTML here (only p tags, no other HTML structure)</p>"
}"""


async def generate_follow_up_content(
    influencer: Influencer,
    follow_up_count: int,
) -> Optional[tuple[str, str]]:
    """
    Generate a differentiated follow-up email (subject, body_html) for the
    given influencer based on their follow_up_count.

    Returns None if OpenAI is not configured or an error occurs (caller should
    use a static fallback).
    """
    settings = get_settings()
    if not settings.openai_api_key:
        logger.warning("OPENAI_API_KEY not set; using static follow-up template")
        return None

    angle_idx = min(follow_up_count, len(_ANGLES) - 1)
    angle = _ANGLES[angle_idx]

    influencer_name = influencer.nickname or influencer.email.split("@")[0]
    platform = influencer.platform.value if influencer.platform else "social media"
    followers_str = f"{influencer.followers:,}" if influencer.followers else "a large audience"
    industry = influencer.industry or "your niche"

    user_prompt = (
        f"Influencer details:\n"
        f"  Name: {influencer_name}\n"
        f"  Platform: {platform}\n"
        f"  Followers: {followers_str}\n"
        f"  Industry: {industry}\n\n"
        f"Follow-up number: {follow_up_count + 1}\n"
        f"Angle to use: {angle}\n\n"
        f"Write a follow-up email using this angle. This is follow-up #{follow_up_count + 1} "
        f"so they have already received the initial outreach and {follow_up_count} previous follow-up(s)."
    )

    try:
        import json
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.8,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        subject = data.get("subject", "").strip()
        body_html = data.get("body_html", "").strip()
        if not subject or not body_html:
            raise ValueError("Missing subject or body_html in GPT response")
        return subject, body_html
    except Exception as exc:
        logger.error("Responder Agent GPT call failed: %s", exc)
        return None


def _static_follow_up(influencer: Influencer, follow_up_count: int) -> tuple[str, str]:
    """Static fallback template when OpenAI is unavailable."""
    name = influencer.nickname or influencer.email.split("@")[0]
    platform = influencer.platform.value if influencer.platform else "social media"
    count = follow_up_count + 1

    subjects = [
        f"Quick follow-up on our collaboration proposal, {name}",
        f"Still interested in working together, {name}?",
        f"One more thought on our collaboration, {name}",
        f"A quick note from us, {name}",
        f"Checking in one last time, {name}",
        f"Keeping the door open, {name}",
    ]
    bodies = [
        f"<p>Hi {name},</p><p>Just wanted to follow up on my previous email about a collaboration opportunity on {platform}. I'd love to connect if you're open to it.</p><p>Best regards</p>",
        f"<p>Hi {name},</p><p>We've had great results with creators on {platform} recently and thought of you again. Would love to explore a partnership if the timing works.</p><p>Best regards</p>",
        f"<p>Hi {name},</p><p>I know your inbox gets busy, so I'll keep this short — we have a campaign I think would be a great fit for your audience. Worth a quick chat?</p><p>Best regards</p>",
        f"<p>Hi {name},</p><p>Still thinking you'd be a great fit for our campaign. Happy to work around your schedule — even a 10-minute call would be great.</p><p>Best regards</p>",
        f"<p>Hi {name},</p><p>I'll keep this brief — we have a limited number of creator spots left for this campaign. If you're at all interested, now is a great time to connect.</p><p>Best regards</p>",
        f"<p>Hi {name},</p><p>I don't want to overwhelm your inbox, so this will be my last follow-up. If you're ever interested in future collaborations, please don't hesitate to reach out. Wishing you continued success!</p><p>Best regards</p>",
    ]

    idx = min(count - 1, len(subjects) - 1)
    return subjects[idx], bodies[idx]


async def get_follow_up_email(
    influencer: Influencer,
    follow_up_count: int,
) -> tuple[str, str]:
    """
    Return (subject, body_html) for a follow-up email.
    Tries GPT-4o first; falls back to static templates.
    """
    result = await generate_follow_up_content(influencer, follow_up_count)
    if result:
        return result
    return _static_follow_up(influencer, follow_up_count)
