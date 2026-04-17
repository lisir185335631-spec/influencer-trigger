import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.template import Template
from app.schemas.template import GeneratedTemplate, TemplateCreate, TemplateUpdate

logger = logging.getLogger(__name__)

# ─── CRUD ─────────────────────────────────────────────────────────────────────


async def list_templates(
    db: AsyncSession,
    industry: str | None = None,
    include_unpublished: bool = False,
) -> list[Template]:
    stmt = select(Template).order_by(Template.created_at.desc())
    if industry:
        stmt = stmt.where(Template.industry == industry)
    if not include_unpublished:
        stmt = stmt.where(Template.is_published == True)  # noqa: E712
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_template(db: AsyncSession, template_id: int) -> Template | None:
    result = await db.execute(select(Template).where(Template.id == template_id))
    return result.scalar_one_or_none()


async def create_template(
    db: AsyncSession, data: TemplateCreate, created_by: int | None = None
) -> Template:
    template = Template(
        name=data.name,
        subject=data.subject,
        body_html=data.body_html,
        industry=data.industry,
        style=data.style,
        language=data.language,
        created_by=created_by,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


async def update_template(
    db: AsyncSession, template_id: int, data: TemplateUpdate
) -> Template | None:
    template = await get_template(db, template_id)
    if not template:
        return None
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    await db.commit()
    await db.refresh(template)
    return template


async def delete_template(db: AsyncSession, template_id: int) -> bool:
    template = await get_template(db, template_id)
    if not template:
        return False
    await db.delete(template)
    await db.commit()
    return True


# ─── AI Generation ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert email copywriter specializing in influencer outreach campaigns.
Generate exactly 3 English email templates for the given industry. Each template should
use a distinct style: formal, casual, and direct.

Supported template variables (use exactly as shown):
- {{influencer_name}}  — the influencer's name
- {{platform}}         — social media platform (e.g. Instagram, TikTok)
- {{followers}}        — follower count
- {{industry}}         — industry/niche

Return a JSON array with exactly 3 objects, each having:
- "style": one of "formal", "casual", "direct"
- "name": short descriptive name for the template (e.g. "Formal Partnership Pitch")
- "subject": email subject line (use variables where natural)
- "body_html": email body as HTML (use <p>, <strong>, <br> tags; include variable placeholders)

Return ONLY the JSON array, no markdown fences, no explanation.
"""


async def generate_templates(industry: str) -> list[GeneratedTemplate]:
    settings = get_settings()

    if not settings.openai_api_key:
        # Return placeholder templates when no API key is configured
        return _placeholder_templates(industry)

    try:
        from app.tools.llm_client import chat as llm_chat

        raw = await llm_chat(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Generate 3 influencer outreach templates for the {industry} industry.",
                },
            ],
            temperature=0.7,
            max_tokens=2000,
        )
        raw = raw or "[]"
        data = json.loads(raw)
        return [GeneratedTemplate(**item) for item in data]

    except Exception as exc:
        logger.error("OpenAI template generation failed: %s", exc)
        raise ValueError(f"AI generation failed: {exc}") from exc


def _placeholder_templates(industry: str) -> list[GeneratedTemplate]:
    """Return sample templates when OpenAI key is not configured."""
    cap_industry = industry.capitalize()
    return [
        GeneratedTemplate(
            style="formal",
            name=f"Formal {cap_industry} Partnership Pitch",
            subject=f"Partnership Opportunity — {{{{influencer_name}}}} × {cap_industry} Brand",
            body_html=(
                f"<p>Dear {{{{influencer_name}}}},</p>"
                f"<p>I hope this message finds you well. My name is [Your Name] and I represent "
                f"a leading brand in the <strong>{cap_industry}</strong> space.</p>"
                f"<p>We have been following your work on <strong>{{{{platform}}}}</strong> and are "
                f"impressed by your engaged audience of <strong>{{{{followers}}}}</strong> followers.</p>"
                f"<p>We would be delighted to explore a potential collaboration that aligns with your "
                f"{{{{industry}}}} content and provides genuine value to your audience.</p>"
                f"<p>Please let me know your availability for a brief call to discuss the details.</p>"
                f"<p>Best regards,<br>[Your Name]</p>"
            ),
        ),
        GeneratedTemplate(
            style="casual",
            name=f"Casual {cap_industry} Collab Outreach",
            subject=f"Hey {{{{influencer_name}}}} — love your {cap_industry} content!",
            body_html=(
                f"<p>Hi {{{{influencer_name}}}}! 👋</p>"
                f"<p>I've been following your {{{{platform}}}} and honestly your {cap_industry} content "
                f"is amazing — the way you connect with your {{{{followers}}}} followers is really special.</p>"
                f"<p>We'd love to work together on something exciting in the {{{{industry}}}} space. "
                f"No pressure at all, just wanted to put it out there!</p>"
                f"<p>Would you be open to a quick chat? Drop me a reply and let's make something cool. 🚀</p>"
                f"<p>Cheers,<br>[Your Name]</p>"
            ),
        ),
        GeneratedTemplate(
            style="direct",
            name=f"Direct {cap_industry} Offer",
            subject=f"Paid collaboration offer for {{{{influencer_name}}}}",
            body_html=(
                f"<p>Hi {{{{influencer_name}}}},</p>"
                f"<p>Quick pitch: we want to pay you to promote our {cap_industry} product to your "
                f"{{{{followers}}}} {{{{platform}}}} followers.</p>"
                f"<p><strong>What we offer:</strong></p>"
                f"<ul><li>Competitive flat fee</li><li>Full creative freedom</li>"
                f"<li>Product samples included</li></ul>"
                f"<p>Interested? Reply with your rate card and we'll move fast.</p>"
                f"<p>[Your Name]</p>"
            ),
        ),
    ]
