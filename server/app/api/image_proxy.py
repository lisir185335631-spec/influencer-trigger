"""
Image proxy — streams remote avatar images (Instagram, TikTok, etc.) through
the backend so that the CDN's Referer check / signed URL can be satisfied
server-side. Browsers can't set Referer reliably, so hotlinking directly to
`scontent-*.cdninstagram.com` from localhost fails. This endpoint fetches
the image with the correct Referer and forwards the bytes.

Auth: intentionally open. The URL being proxied comes from already-authorized
API responses (influencer list, scrape results) — proxying public CDN assets
does not expose anything new. SSRF is prevented by a strict host allow-list.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response, StreamingResponse

router = APIRouter(tags=["image-proxy"])

# Exact-host or suffix match — any remote whose hostname ends with one of
# these strings is allowed. Keep tight; expand as new platforms ship.
_ALLOWED_HOST_SUFFIXES: tuple[str, ...] = (
    # Instagram / Facebook CDN
    ".cdninstagram.com",
    ".fbcdn.net",
    # YouTube (direct-load already works, but proxy is a harmless fallback)
    "yt3.ggpht.com",
    "yt3.googleusercontent.com",
    "lh3.googleusercontent.com",
    "i.ytimg.com",
    # Twitter / X
    "pbs.twimg.com",
    # TikTok
    ".tiktokcdn.com",
    ".tiktokcdn-us.com",
    ".bytecdn.cn",
)

# Per-host Referer to satisfy CDN hotlink checks. Keys are suffixes matched
# the same way as the allow-list. First match wins.
_REFERER_BY_SUFFIX: tuple[tuple[str, str], ...] = (
    (".cdninstagram.com", "https://www.instagram.com/"),
    (".fbcdn.net", "https://www.facebook.com/"),
    ("pbs.twimg.com", "https://twitter.com/"),
    (".tiktokcdn.com", "https://www.tiktok.com/"),
    (".tiktokcdn-us.com", "https://www.tiktok.com/"),
)

_IMAGE_CT_RE = re.compile(r"^image/", re.IGNORECASE)

# Avatars are typically 50-300 KB; 5 MB is a generous cap that catches
# attacker / mis-encoded responses without rejecting any legit avatar we've
# observed. The proxy used to stream arbitrary sizes, which left the browser
# vulnerable to an upstream CDN compromise (or an attacker forging a CDN
# response in any path that loops to `/api/image-proxy`).
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB


def _is_host_allowed(host: str) -> bool:
    host = (host or "").lower()
    return any(host == s.lstrip(".") or host.endswith(s) for s in _ALLOWED_HOST_SUFFIXES)


def _referer_for(host: str) -> str | None:
    host = (host or "").lower()
    for suffix, ref in _REFERER_BY_SUFFIX:
        if host == suffix.lstrip(".") or host.endswith(suffix):
            return ref
    return None


@router.get("/image-proxy")
async def image_proxy(url: str = Query(..., max_length=2048)) -> Response:
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="invalid url")
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="invalid url")
    if not _is_host_allowed(parsed.hostname or ""):
        raise HTTPException(status_code=403, detail="host not allowed")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    ref = _referer_for(parsed.hostname or "")
    if ref:
        headers["Referer"] = ref

    try:
        client = httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True)
        resp = await client.get(url)
    except Exception:
        raise HTTPException(status_code=502, detail="upstream fetch failed")

    if resp.status_code != 200:
        await client.aclose()
        raise HTTPException(status_code=502, detail=f"upstream status {resp.status_code}")

    content_type = resp.headers.get("content-type", "image/jpeg")
    if not _IMAGE_CT_RE.match(content_type):
        await client.aclose()
        raise HTTPException(status_code=502, detail="upstream is not an image")

    # Pre-flight size check via declared Content-Length. Cheap reject before
    # we start streaming — saves both bandwidth and avoids handing partial
    # bytes to the browser.
    declared_len = resp.headers.get("content-length")
    if declared_len is not None:
        try:
            if int(declared_len) > _MAX_IMAGE_BYTES:
                await resp.aclose()
                await client.aclose()
                raise HTTPException(status_code=413, detail="upstream image too large")
        except ValueError:
            # malformed Content-Length — fall through to stream-time guard
            pass

    async def _stream():
        total = 0
        try:
            async for chunk in resp.aiter_bytes(8192):
                total += len(chunk)
                if total > _MAX_IMAGE_BYTES:
                    # Streaming-time guard for upstreams that lie about (or
                    # omit) Content-Length. We can't change the HTTP status
                    # mid-response — the client gets a truncated image, which
                    # is acceptable since this only fires on adversarial /
                    # broken CDN responses (legit avatars are <300KB).
                    break
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    response_headers = {
        # Avatar URLs on IG CDN rotate every few weeks; 24h cache is a
        # good tradeoff between hit rate and freshness.
        "Cache-Control": "public, max-age=86400",
        "X-Content-Type-Options": "nosniff",
    }
    # Forward the upstream Content-Length when known and within cap, so the
    # browser can show a progress bar for slow loads. (Skipped if absent or
    # malformed; StreamingResponse handles chunked-transfer in that case.)
    if declared_len is not None:
        try:
            cl_int = int(declared_len)
            if 0 <= cl_int <= _MAX_IMAGE_BYTES:
                response_headers["Content-Length"] = str(cl_int)
        except ValueError:
            pass

    return StreamingResponse(
        _stream(),
        media_type=content_type,
        headers=response_headers,
    )
