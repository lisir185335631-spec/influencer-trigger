interface AvatarBadgeProps {
  url?: string | null
  name?: string | null
  size?: number
}

export default function AvatarBadge({ url, name, size = 24 }: AvatarBadgeProps) {
  const initials = (name || '?').trim().charAt(0).toUpperCase()
  const style = { width: size, height: size }
  if (url) {
    return (
      <img
        src={url}
        alt={name || ''}
        style={style}
        className="rounded-full object-cover bg-gray-100 flex-shrink-0"
        onError={(e) => {
          // 图片加载失败 → 换成首字母
          ;(e.target as HTMLImageElement).style.display = 'none'
        }}
      />
    )
  }
  // fallback 首字母 monogram
  return (
    <span
      style={style}
      className="rounded-full bg-gradient-to-br from-gray-100 to-gray-200 text-gray-500 flex items-center justify-center text-[10px] font-medium flex-shrink-0"
    >
      {initials}
    </span>
  )
}
