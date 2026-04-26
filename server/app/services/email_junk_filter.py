"""Email junk filter — rejects placeholder / role / template emails BEFORE
they get inserted as influencer records.

Rationale (motivated by task #55):
  Apify's TikTok email scraper with `scrapeEmails=True` follows external bio
  links and harvests every email it finds on the landing page. That sweeps in
  third-party content like Apple iPhone marketing screenshots (which famously
  show `johnappleseed@gmail.com`), affiliate-marketplace `support@` addresses,
  and template-page boilerplate. None of those are real creator contacts.

  The existing `EmailBlacklist` model is for the sending side (specific
  addresses we've decided not to email). This filter is upstream of insertion
  — it stops junk from ever becoming an "influencer" in the first place.

Two layers:
  1. Local-part patterns — universal, no surrounding context needed
     (e.g. `johnappleseed@*` is junk regardless of domain)
  2. Whole-domain blacklist — for domains where every address is non-creator
     (e.g. `clickbank.com` only ever yields support@clickbank.com)

Returns (is_junk, reason) so callers can log WHY a given email was dropped —
crucial for tuning the blacklist without losing the audit trail.
"""
from __future__ import annotations

import re

# Local-part exact matches. The `@` is implied — these match the part before @
# regardless of which domain follows. Lower-cased; comparison is case-insensitive.
_LOCAL_PART_EXACT = frozenset({
    # Apple's "John Appleseed" — appears in iPhone marketing photos / keynote
    # screenshots that scrapeEmails=True harvests when it visits external links.
    "johnappleseed",
    # English-locale placeholder names from form templates / lorem-ipsum samples.
    "john.doe", "johndoe", "jane.doe", "janedoe",
    # UI / tutorial template literals.
    "your.name", "yourname", "youremail", "your.email",
    "name", "email", "user", "username",
    # Test / demo / sample placeholders.
    "test", "demo", "sample", "example", "placeholder", "dummy", "foo", "bar",
    # No-reply addresses (auto-mailers, can't actually receive replies).
    "noreply", "no-reply", "donotreply", "do-not-reply", "no_reply",
    # RFC 2142 reserved role aliases — administrative, not personal.
    "postmaster", "webmaster", "abuse", "hostmaster", "security", "ssl-admin",
})

# Local-part prefix patterns (start with).
# Conservative: only obvious-junk prefixes, not common ones like "info" or
# "support" which legitimate creators sometimes use for brand contact.
_LOCAL_PART_PREFIXES = (
    "test_", "test-", "test.",
    "demo_", "demo-", "demo.",
    "sample_", "sample-", "sample.",
    "example_", "example-", "example.",
)

# Whole-domain blacklist. ANY email at these domains is rejected.
_DOMAIN_BLACKLIST = frozenset({
    # RFC reserved domains — can never be real.
    "example.com", "example.org", "example.net",
    "test.com", "test.org", "domain.com", "email.com", "mail.com",
    "yourdomain.com", "yoursite.com", "website.com",

    # Affiliate marketplaces — `support@` here is platform staff, not creator.
    # If a TikTok creator's bio links to a clickbank product page, scrapeEmails
    # picks up clickbank's own support address.
    "clickbank.com", "digistore24.com", "jvzoo.com", "warriorplus.com",
    "shareasale.com", "cj.com", "impact.com", "rakuten.com",
    "awin.com", "partnerstack.com",

    # Big tech corp domains — these are platform/corporate addresses,
    # never individual creators contacted via TikTok.
    "apple.com", "facebook.com", "instagram.com", "tiktok.com",
    "youtube.com", "google.com", "microsoft.com", "twitter.com",
    "x.com", "linkedin.com", "meta.com",

    # Disposable / temporary mail services — by design unreachable.
    "tempmail.com", "mailinator.com", "guerrillamail.com", "10minutemail.com",
    "yopmail.com", "throwaway.email", "trashmail.com", "fakeinbox.com",
    "maildrop.cc", "getairmail.com", "mintemail.com",
})

# Domain regex blacklist — matches subdomain variants (anything ending in
# these suffixes). Keep this list small; mostly for parametric junk.
_DOMAIN_SUFFIX_BLACKLIST = (
    ".example",
    ".test",
    ".invalid",
    ".localhost",
)


_EMAIL_RE = re.compile(r"^([^@]+)@([^@]+)$")


def is_junk_email(email: str) -> tuple[bool, str | None]:
    """Return (is_junk, reason). reason is None when not junk.

    Always lowercases for comparison. Empty / malformed input is treated as
    junk (caller should pre-validate format if it cares to distinguish).
    """
    if not email:
        return True, "empty"
    e = email.strip().lower()
    m = _EMAIL_RE.match(e)
    if not m:
        return True, "malformed"
    local, domain = m.group(1), m.group(2)

    if domain in _DOMAIN_BLACKLIST:
        return True, f"blacklisted_domain:{domain}"

    for suffix in _DOMAIN_SUFFIX_BLACKLIST:
        if domain.endswith(suffix):
            return True, f"blacklisted_domain_suffix:{suffix}"

    if local in _LOCAL_PART_EXACT:
        return True, f"placeholder_local_part:{local}"

    for prefix in _LOCAL_PART_PREFIXES:
        if local.startswith(prefix):
            return True, f"placeholder_local_prefix:{prefix}"

    return False, None
