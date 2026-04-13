"""
Classifier Agent — Reply intent classification via GPT-4o-mini.

Architecture: LangGraph single-node graph.
State: ClassifierState receives reply_content; the classify node emits
      intent / confidence / summary back into the state.

Intent categories:
  interested   — influencer wants to collaborate or learn more
  pricing      — influencer asking about rates / budget
  declined     — explicit refusal
  auto_reply   — out-of-office / automated acknowledgment
  irrelevant   — spam or unrelated
"""
import logging
from typing import Optional

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field
from typing_extensions import TypedDict

from app.config import get_settings
from app.models.influencer import ReplyIntent

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output schema (Pydantic v2, compatible with with_structured_output)
# ---------------------------------------------------------------------------

class ClassifyResult(BaseModel):
    intent: str = Field(
        description=(
            "Exactly one of: interested, pricing, declined, auto_reply, irrelevant"
        )
    )
    confidence: float = Field(
        description="Confidence score between 0.0 and 1.0"
    )
    summary: str = Field(
        description="One-sentence English summary of the reply, max 100 characters"
    )


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

class ClassifierState(TypedDict):
    reply_content: str
    result: Optional[ClassifyResult]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are a reply intent classifier for an influencer marketing system.

Classify the influencer's reply email into exactly ONE of these 5 categories:
- interested : influencer is interested in collaboration, wants to know more, or asks follow-up questions
- pricing    : influencer asks about rates, budget, payment, or compensation
- declined   : influencer explicitly says no or is not interested
- auto_reply : automated out-of-office, vacation notice, or auto-acknowledgment
- irrelevant : spam, unrelated content, or cannot be categorised above

Return ONLY valid JSON with these three keys:
  "intent"     : one of the 5 categories (string)
  "confidence" : float 0.0–1.0
  "summary"    : one-sentence English description of the reply (max 100 chars)"""

_PROMPT = ChatPromptTemplate.from_messages([
    ("system", _SYSTEM_PROMPT),
    ("human", "Reply content:\n{reply_content}"),
])

_VALID_INTENTS = {e.value for e in ReplyIntent}


# ---------------------------------------------------------------------------
# Graph builder (lazy singleton)
# ---------------------------------------------------------------------------

def _build_graph():
    settings = get_settings()

    llm = ChatOpenAI(
        model=settings.openai_classifier_model,
        api_key=settings.openai_api_key,
        temperature=0,
    ).with_structured_output(ClassifyResult)

    async def classify_node(state: ClassifierState) -> dict:
        try:
            chain = _PROMPT | llm
            result: ClassifyResult = await chain.ainvoke(
                {"reply_content": state["reply_content"][:2000]}
            )
            # Sanitise intent in case the model returns an unexpected value
            if result.intent not in _VALID_INTENTS:
                logger.warning(
                    "Classifier returned unknown intent %r; falling back to irrelevant",
                    result.intent,
                )
                result.intent = "irrelevant"
            result.confidence = max(0.0, min(1.0, result.confidence))
            result.summary = result.summary[:100]
            return {"result": result}
        except Exception as exc:
            logger.error("Classifier LLM call failed: %s", exc)
            return {
                "result": ClassifyResult(
                    intent="irrelevant",
                    confidence=0.0,
                    summary="Classification failed",
                )
            }

    graph = StateGraph(ClassifierState)
    graph.add_node("classify", classify_node)
    graph.add_edge(START, "classify")
    graph.add_edge("classify", END)
    return graph.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def classify_reply(reply_content: str) -> ClassifyResult:
    """
    Classify a reply email's intent using GPT-4o-mini via a LangGraph graph.

    Returns ClassifyResult(intent, confidence, summary).
    Falls back to intent='irrelevant', confidence=0.0 on any error or missing
    API key.
    """
    if not get_settings().openai_api_key:
        logger.warning("OPENAI_API_KEY not configured; skipping classification")
        return ClassifyResult(
            intent="irrelevant",
            confidence=0.0,
            summary="No API key configured",
        )

    graph = _get_graph()
    output = await graph.ainvoke(
        {"reply_content": reply_content, "result": None}
    )
    return output["result"]
