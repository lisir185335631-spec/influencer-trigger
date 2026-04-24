import { useState, useEffect } from 'react'

interface AvatarBadgeProps {
  url?: string | null
  name?: string | null
  size?: number
}

// Hosts whose images require server-side Referer to load — cross-origin
// fetches from the browser get 403'd. The backend /api/image-proxy fills in
// the right Referer and streams the bytes. YouTube is intentionally excluded:
// `yt3.*` accepts no-referrer just fine, and direct-loading saves a backend hop.
const _PROXY_HOST_SUFFIXES = [
  '.cdninstagram.com',
  '.fbcdn.net',
  'pbs.twimg.com',
  '.tiktokcdn.com',
  '.tiktokcdn-us.com',
]

function _needsProxy(url: string): boolean {
  try {
    const host = new URL(url).hostname.toLowerCase()
    return _PROXY_HOST_SUFFIXES.some((s) =>
      host === s.replace(/^\./, '') || host.endsWith(s),
    )
  } catch {
    return false
  }
}

function _resolveImgSrc(url: string): string {
  return _needsProxy(url) ? `/api/image-proxy?url=${encodeURIComponent(url)}` : url
}

export default function AvatarBadge({ url, name, size = 24 }: AvatarBadgeProps) {
  // Track load failure per-url so changing inputs reset the fallback state.
  const [failed, setFailed] = useState(false)
  useEffect(() => { setFailed(false) }, [url])

  const initials = (name || '?').trim().charAt(0).toUpperCase()
  const style = { width: size, height: size }

  if (url && !failed) {
    const resolved = _resolveImgSrc(url)
    return (
      <img
        src={resolved}
        alt={name || ''}
        style={style}
        className="rounded-full object-cover bg-gray-100 flex-shrink-0"
        // no-referrer sidesteps YouTube CDN hotlink rejection when the page is
        // served from localhost or a non-YouTube origin. Proxy-wrapped URLs
        // are same-origin so referrer behavior doesn't matter for them.
        referrerPolicy="no-referrer"
        loading="lazy"
        onError={() => setFailed(true)}
      />
    )
  }
  // fallback 首字母 monogram — shown when url missing OR image load failed
  // (e.g. ad-blocker on yt3.googleusercontent.com, CORS, DNS error).
  return (
    <span
      style={style}
      className="rounded-full bg-gradient-to-br from-gray-100 to-gray-200 text-gray-500 flex items-center justify-center text-[10px] font-medium flex-shrink-0"
      title={name || ''}
    >
      {initials}
    </span>
  )
}
