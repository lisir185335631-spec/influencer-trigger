"""Regression tests for `_industry_relevance_prefilter`.

The 2026-04-25 relaxation (task #65 root-cause work) lowered the follower
bypass from 50K → 5K and added a business-intent bypass. This test set
locks in:
  - the 5 channels from task #65 that were rejected pre-fix and should
    now pass (real creators with collab signals)
  - off-topic channels that should still be rejected (English vlog
    bios with no industry tokens and no business signal)
  - edge cases: empty bio, empty industry, large channel
"""
from app.agents.scraper import _industry_relevance_prefilter as gate


# ── Cases lifted from task #65 logs ──────────────────────────────────────
# The 5 channels below all had emails and were prefilter-REJECTed pre-fix,
# wasting them as candidates. After the fix, the ones with collab signals
# pass; the truly off-topic ones still fail (which is correct).

def test_blackmagic_with_contact_keyword_passes():
    """黑魔法 — followers=42800, bio explicitly says '联系方式'."""
    bio = "硬核知识，简洁日常。联系方式：blackmagican@example.com"
    assert gate("AI 工具", bio, "黑魔法", 42_800) is True


def test_xiaomi_xueshe_with_buy_me_coffee_collab_passes():
    """小米学社 — followers=20800, bio mentions '合作' implicitly via tip jar."""
    bio = "欢迎你 Buy Me a Coffee 请我喝一杯，商务合作请联系：xiaomi@example.com"
    assert gate("AI 工具", bio, "小米学社", 20_800) is True


def test_jingguan_dianlu_with_jiaoxue_passes_via_industry_token():
    """静观点录 — bio: '...教学频道...常年累积...AI...' — has '工具'-adjacent
    content but the literal 'ai 工具' token is hit by 'ai'."""
    bio = "静观点录，专注 ai 教学频道，分享日常..."
    assert gate("AI 工具", bio, "静观点录", 4) is True


def test_dr_izzy_off_topic_english_bio_still_rejected():
    """Dr. Izzy Sealey — followers=14, English personal-growth bio with
    NO industry tokens AND no business signal. Should still REJECT."""
    bio = "Hey there, I'm Izzy. I make videos about personal growth to help you."
    assert gate("AI 工具", bio, "Dr. Izzy Sealey", 14) is False


def test_nancy_shen_with_ai_in_bio_passes():
    """Nancy Shen — followers=1850, bio mentions AI; pre-fix the 1850
    follower count plus narrow token gate was rejecting; post-fix the
    'ai' literal hits + the tip is small enough that bypass tier helps."""
    bio = "斯坦福双学位博士、AI 教育、机器学习、数据科学..."
    assert gate("AI 工具", bio, "Nancy Shen", 1_850) is True


# ── Bypass tiers ─────────────────────────────────────────────────────────

def test_large_channel_bypasses_via_followers():
    """Large channels (>=5K) bypass token check — LLM enrichment grades."""
    bio = "Random gaming highlights and reactions"
    assert gate("AI 工具", bio, "GamingChannel", 50_000) is True


def test_small_channel_with_collab_signal_bypasses():
    """Even a tiny channel with explicit business intent bypasses."""
    bio = "Looking for brand partnerships, contact me at hello@example.com"
    assert gate("AI 工具", bio, "TinyKOL", 200) is True


def test_collab_bypass_chinese_keyword():
    """Chinese collab keyword '商务' triggers bypass."""
    bio = "美食博主分享日常，商务合作请邮件"
    assert gate("AI 工具", bio, "FoodBlogger", 100) is True


# ── Edge cases ───────────────────────────────────────────────────────────

def test_empty_industry_passes():
    assert gate("", "anything", "name", 0) is True
    assert gate(None, "anything", "name", 0) is True


def test_empty_bio_and_nickname_passes():
    """No text to evaluate → defer to LLM enrichment, don't reject."""
    assert gate("AI 工具", "", "", 0) is True
    assert gate("AI 工具", None, None, None) is True


def test_industry_token_in_nickname_passes():
    """nickname is part of the searchable text — '工具' in name passes."""
    assert gate("AI 工具", "anything random", "AI 工具控", 100) is True


def test_short_token_only_industry_still_passes():
    """Industry that tokenises to nothing usable defers to LLM."""
    # '/' splits everything, leaves only single chars
    assert gate("a/b/c", "unrelated bio", "name", 100) is True


def test_off_topic_creator_with_no_signals_rejected():
    """Real off-topic content + no business signal + small followers → reject."""
    bio = "Daily yoga and meditation videos to start your morning right."
    assert gate("Power Bank", bio, "YogaWithSara", 800) is False
