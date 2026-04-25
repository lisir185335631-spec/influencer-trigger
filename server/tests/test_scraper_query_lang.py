"""Unit tests for the scraper's query-language validator.

These tests cover the regression fixed in commit 892d1c5: when
target_market is CJK (cn/tw/jp/kr), short Latin proper nouns (KOL handles
and brand names like 'MKBHD' / 'Linus Tech Tips' / 'ChatGPT') must NOT be
dropped — the search-strategy prompt asks the LLM to mix them in. Long
English sentences (4+ tokens) are still rejected because those are
genuine mistranslations the validator was originally designed to catch.

Without these tests, a future refactor of `_query_matches_lang` could
silently re-introduce the task #44 bug (8/12 queries dropped, candidate
pool halved).

Run: cd server && .venv/Scripts/python -m pytest tests/test_scraper_query_lang.py -v
"""
from __future__ import annotations

import pytest

from app.agents.scraper import (
    _expected_query_lang,
    _is_cjk_text,
    _query_matches_lang,
)


# ── _is_cjk_text ────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected", [
    ("AI tools", False),
    ("MKBHD", False),
    ("ChatGPT review", False),
    ("AI 工具", True),
    ("AI工具", True),
    ("ChatGPT 評測", True),
    ("ai ツール", True),     # Hiragana
    ("使い方", True),        # Hiragana
    ("Anker_韓国", True),    # mixed
    ("한국어", True),         # Hangul
    ("", False),
])
def test_is_cjk_text(text, expected):
    assert _is_cjk_text(text) == expected


# ── _expected_query_lang ────────────────────────────────────────────────

@pytest.mark.parametrize("industry,market,expected", [
    # Explicit market wins
    ("ai tools", "us", "en"),
    ("ai tools", "tw", "tw"),
    ("ai 工具", "us", "en"),  # market overrides industry script
    ("ai 工具", "cn", "cn"),
    ("ai tools", "jp", "jp"),
    ("ai tools", "kr", "kr"),
    # Unknown / empty market: read industry script
    ("ai tools", None, "en"),
    ("ai 工具", None, "cn"),
    ("ai 工具", "", "cn"),    # empty market: falls through to industry script — CJK industry → 'cn'
    ("", "kr", "kr"),
    # Mixed-case markets normalize
    ("ai tools", "US", "en"),
    ("ai tools", "TW", "tw"),
])
def test_expected_query_lang(industry, market, expected):
    assert _expected_query_lang(industry, market) == expected


# Re-test the CJK-industry-with-empty-market case explicitly (above
# parametrize had a borderline case).
def test_expected_lang_cjk_industry_no_market():
    assert _expected_query_lang("ai 工具", "") == "cn"


# ── _query_matches_lang: lang=en (Latin only) ───────────────────────────

@pytest.mark.parametrize("query,expected", [
    # Latin-only queries pass
    ("AI tools tutorial for creators", True),
    ("Best AI tools 2026", True),
    ("MKBHD", True),
    ("Linus Tech Tips", True),
    # CJK queries are dropped (the original task #27 bug)
    ("AI 工具推荐", False),
    ("AI工具", False),
    ("ChatGPT 評測", False),  # any CJK → reject
])
def test_query_matches_lang_en(query, expected):
    assert _query_matches_lang(query, "en") == expected


# ── _query_matches_lang: CJK markets with CJK queries (always pass) ────

@pytest.mark.parametrize("query,lang", [
    ("AI 工具 教學", "tw"),
    ("AI 工具 評測", "tw"),
    ("AI 工具 推薦", "tw"),
    ("AI 工具 商務合作", "tw"),
    ("AI 工具 教程", "cn"),
    ("AI 工具 评测", "cn"),
    ("AI ツール 使い方", "jp"),
    ("AI 도구 추천", "kr"),
])
def test_query_matches_lang_cjk_with_cjk(query, lang):
    assert _query_matches_lang(query, lang) is True


# ── _query_matches_lang: CJK markets with short Latin proper nouns ─────
# The 892d1c5 regression fix. These MUST pass — pre-fix they were dropped
# and task #44 lost 8/12 queries.

@pytest.mark.parametrize("query,lang", [
    # Single-word brand / KOL names
    ("MKBHD", "tw"),
    ("Dave2D", "tw"),
    ("iJustine", "tw"),
    ("Mrwhosetheboss", "tw"),
    ("ChatGPT", "cn"),
    ("Anker", "jp"),
    # Two-word brand / KOL names
    ("Marques Brownlee", "tw"),
    ("Notion AI", "cn"),
    ("Matt Wolfe", "tw"),
    ("Wes Roth", "tw"),
    # Three-word KOL names
    ("Linus Tech Tips", "tw"),
    ("Greg Isenberg", "tw"),
])
def test_query_matches_lang_short_latin_in_cjk_pass(query, lang):
    assert _query_matches_lang(query, lang) is True, (
        f"Short Latin proper noun {query!r} should pass for lang={lang} "
        f"(pre-fix bug: it was dropped, halving the candidate pool)"
    )


# ── _query_matches_lang: long Latin sentences in CJK markets (rejected) ─
# These are the cases the validator was originally designed to catch:
# the LLM mistakenly produced English when target_market was CJK.

@pytest.mark.parametrize("query,lang", [
    ("AI tools tutorial for creators", "tw"),       # 5 tokens
    ("Best practices for AI subscription", "tw"),   # 5 tokens
    ("How to use AI in Japan", "jp"),               # 6 tokens
    ("Comparison of AI tools for marketing", "cn"), # 6 tokens
])
def test_query_matches_lang_long_latin_in_cjk_reject(query, lang):
    assert _query_matches_lang(query, lang) is False, (
        f"Long Latin sentence {query!r} should be rejected for lang={lang} "
        f"(LLM forgot to translate; fallback should kick in)"
    )


# ── Boundary: exactly 3 vs 4 tokens at the cliff ────────────────────────

def test_query_matches_lang_three_token_boundary_passes():
    """3-token Latin in CJK market: still treated as proper noun."""
    assert _query_matches_lang("Linus Media Group", "tw") is True


def test_query_matches_lang_four_token_boundary_rejects():
    """4-token Latin in CJK market: treated as accidental English."""
    assert _query_matches_lang("Best AI tools today", "tw") is False
