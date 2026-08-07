// 视频与图集的归一化层：把两类资源统一为 MediaItem，使收藏/点赞/不喜欢/历史
// 等「我的」页面可以平等地合并展示，而不再只认视频。
import { videoApi, galleryApi, historyApi } from '../api'
import { useUserStore } from '../stores/userStore'

/**
 * 为受资源库权限保护的封面/缩略图地址追加 token 查询参数。
 * JWT 登录模式下浏览器原生 <img> 请求无法携带 Authorization 头，
 * /thumbnail/、/gallery-cover/ 等接口需要 token 才能访问非公开库资源。
 */
export function withThumbToken(url?: string | null): string {
  if (!url) return '/placeholder.jpg'
  const token = useUserStore().token
  if (token && (url.startsWith('/thumbnail/') || url.startsWith('/gallery-cover/'))) {
    const sep = url.includes('?') ? '&' : '?'
    return url + sep + 'token=' + token
  }
  return url
}

export type MediaType = 'video' | 'gallery'

export interface MediaItem {
  type: MediaType
  hash: string
  title: string
  cover: string          // 卡片封面（视频=thumbnail，图集=cover_url）
  thumbnail?: string
  duration?: number      // 视频时长（秒）
  pageCount?: number     // 图集页数
  progress?: number      // 0~1，历史进度展示用
  page?: number          // 图集当前阅读页
  date?: string          // 交互/历史时间（用于排序与展示）
  location?: string      // 磁盘位置（管理员可见，权限控制）
  size?: number          // 文件大小（字节，管理员可见，权限控制）
  raw?: any              // 原始接口数据
}

function normalizeVideo(v: any): MediaItem {
  return {
    type: 'video',
    hash: v.hash,
    title: v.title,
    cover: v.thumbnail || '',
    thumbnail: v.thumbnail,
    duration: v.duration,
    progress: typeof v.progress === 'number' ? v.progress : undefined,
    date: v.favorited_at || v.liked_at || v.disliked_at || v.watched_at || v.updated_at,
    location: v.local_path,
    size: typeof v.file_size === 'number' ? v.file_size : undefined,
    raw: v
  }
}

function normalizeGallery(c: any): MediaItem {
  return {
    type: 'gallery',
    hash: c.hash,
    title: c.title,
    cover: c.cover_url || '',
    pageCount: c.page_count,
    progress: typeof c.progress === 'number' ? c.progress : undefined,
    page: c.page ?? c.last_page,
    date: c.favorited_at || c.liked_at || c.disliked_at || c.updated_at,
    location: c.folder_path,
    size: typeof c.size === 'number' ? c.size : undefined,
    raw: c
  }
}

function sortByDateDesc(items: MediaItem[]): MediaItem[] {
  return items.sort((a, b) => {
    const ta = a.date ? Date.parse(a.date) : 0
    const tb = b.date ? Date.parse(b.date) : 0
    return (isNaN(tb) ? 0 : tb) - (isNaN(ta) ? 0 : ta)
  })
}

// 收藏 / 点赞 / 不喜欢：同时取视频与图集，合并后按时间倒序
export async function fetchFavorites(): Promise<MediaItem[]> {
  const [v, c] = await Promise.all([
    videoApi.getFavorites() as any,
    galleryApi.getFavorites() as any
  ])
  const items: MediaItem[] = []
  if (v?.success && Array.isArray(v.videos)) items.push(...v.videos.map(normalizeVideo))
  if (c?.success && Array.isArray(c.galleries)) items.push(...c.galleries.map(normalizeGallery))
  return sortByDateDesc(items)
}

export async function fetchLikes(): Promise<MediaItem[]> {
  const [v, c] = await Promise.all([
    videoApi.getLikes() as any,
    galleryApi.getLikes() as any
  ])
  const items: MediaItem[] = []
  if (v?.success && Array.isArray(v.videos)) items.push(...v.videos.map(normalizeVideo))
  if (c?.success && Array.isArray(c.galleries)) items.push(...c.galleries.map(normalizeGallery))
  return sortByDateDesc(items)
}

export async function fetchDisliked(): Promise<MediaItem[]> {
  const [v, c] = await Promise.all([
    videoApi.getDisliked() as any,
    galleryApi.getDisliked() as any
  ])
  const items: MediaItem[] = []
  if (v?.success && Array.isArray(v.videos)) items.push(...v.videos.map(normalizeVideo))
  if (c?.success && Array.isArray(c.galleries)) items.push(...c.galleries.map(normalizeGallery))
  return sortByDateDesc(items)
}

// 历史：视频与图集均以后端 /api/history 为唯一数据源（登录账号跨设备一致）
export async function fetchHistory(): Promise<MediaItem[]> {
  const res = (await historyApi.getHistory()) as any
  if (!res?.success || !Array.isArray(res.items)) return []
  const items: MediaItem[] = res.items.map((h: any) => ({
    type: h.itemType,
    hash: h.itemId,
    title: h.title,
    cover: h.thumbnail || '',
    thumbnail: h.thumbnail,
    duration: h.duration || 0,
    progress: h.progress || 0,
    date: h.watchedAt,
    _historySource: h.itemType,
  }))
  return sortByDateDesc(items)
}

// 混排信息流由 Posts.vue（/api/posts）按 mode=mixed 统一承载，
// 融合视频/图集/文本多类型资源，不再单独维护视频+图集聚合函数。
