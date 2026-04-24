import { useState, useEffect } from 'react'

interface AvatarBadgeProps {
  url?: string | null
  name?: string | null
  size?: number
}

export default function AvatarBadge({ url, name, size = 24 }: AvatarBadgeProps) {
  // Track load failure per-url so changing inputs reset the fallback state.
  const [failed, setFailed] = useState(false)
  useEffect(() => { setFailed(false) }, [url])

  const initials = (name || '?').trim().charAt(0).toUpperCase()
  const style = { width: size, height: size }

  if (url && !failed) {
    return (
      <img
        src={url}
        alt={name || ''}
        style={style}
        className="rounded-full object-cover bg-gray-100 flex-shrink-0"
        // no-referrer sidesteps YouTube CDN hotlink rejection when the page is
        // served from localhost or a non-YouTube origin.
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
