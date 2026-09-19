// 时长格式化工具：统一此前散落在 Video / Review / Home / Admin / VideoCard /
// MediaCard 的内联实现。秒 -> "MM:SS" 或 "H:MM:SS"；非法/缺失值返回 "00:00"。
export function formatDuration(seconds?: number | null): string {
  if (seconds == null || !isFinite(seconds) || seconds <= 0) return '00:00'
  const total = Math.floor(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

// 字节数 -> 人类可读（B/KB/MB/GB/TB，1 位小数，B 取整）。统一此前散落在
// Disliked / Admin / Review 的内联实现；非法/缺失值返回 "0 B"。
export function formatSize(bytes?: number | null): string {
  if (bytes == null || !isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}
