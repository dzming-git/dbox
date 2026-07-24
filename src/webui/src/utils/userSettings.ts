// 读取并解析本地设置（保存在 localStorage 的 'userSettings'）
export function loadUserSettings(): any {
  try {
    const raw = localStorage.getItem('userSettings')
    if (raw) return JSON.parse(raw)
  } catch {
    // 忽略解析错误，回退到空对象
  }
  return {}
}

// 用户自定义默认排序（视频 / 漫画列表首页通用）
// 返回 { sort, order }；未设置时回退到 'recommended' / 'desc'
export function getDefaultSort(): { sort: string; order: string } {
  const s = loadUserSettings()
  return {
    sort: s.defaultSort || 'recommended',
    order: s.defaultOrder || 'desc'
  }
}
