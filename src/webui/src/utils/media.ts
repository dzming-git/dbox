// 视频与漫画的归一化层：把两类资源统一为 MediaItem，使收藏/点赞/不喜欢/历史
// 等「我的」页面可以平等地合并展示，而不再只认视频。
import { videoApi, comicApi } from '../api'

export type MediaType = 'video' | 'comic'

export interface MediaItem {
  type: MediaType
  hash: string
  title: string
  cover: string          // 卡片封面（视频=thumbnail，漫画=cover_url）
  thumbnail?: string
  duration?: number      // 视频时长（秒）
  pageCount?: number     // 漫画页数
  progress?: number      // 0~1，历史进度展示用
  page?: number          // 漫画当前阅读页
  date?: string          // 交互/历史时间（用于排序与展示）
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
    raw: v
  }
}

function normalizeComic(c: any): MediaItem {
  return {
    type: 'comic',
    hash: c.hash,
    title: c.title,
    cover: c.cover_url || '',
    pageCount: c.page_count,
    progress: typeof c.progress === 'number' ? c.progress : undefined,
    page: c.page ?? c.last_page,
    date: c.favorited_at || c.liked_at || c.disliked_at || c.updated_at,
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

// 收藏 / 点赞 / 不喜欢：同时取视频与漫画，合并后按时间倒序
export async function fetchFavorites(): Promise<MediaItem[]> {
  const [v, c] = await Promise.all([
    videoApi.getFavorites() as any,
    comicApi.getFavorites() as any
  ])
  const items: MediaItem[] = []
  if (v?.success && Array.isArray(v.videos)) items.push(...v.videos.map(normalizeVideo))
  if (c?.success && Array.isArray(c.comics)) items.push(...c.comics.map(normalizeComic))
  return sortByDateDesc(items)
}

export async function fetchLikes(): Promise<MediaItem[]> {
  const [v, c] = await Promise.all([
    videoApi.getLikes() as any,
    comicApi.getLikes() as any
  ])
  const items: MediaItem[] = []
  if (v?.success && Array.isArray(v.videos)) items.push(...v.videos.map(normalizeVideo))
  if (c?.success && Array.isArray(c.comics)) items.push(...c.comics.map(normalizeComic))
  return sortByDateDesc(items)
}

export async function fetchDisliked(): Promise<MediaItem[]> {
  const [v, c] = await Promise.all([
    videoApi.getDisliked() as any,
    comicApi.getDisliked() as any
  ])
  const items: MediaItem[] = []
  if (v?.success && Array.isArray(v.videos)) items.push(...v.videos.map(normalizeVideo))
  if (c?.success && Array.isArray(c.comics)) items.push(...c.comics.map(normalizeComic))
  return sortByDateDesc(items)
}

// 历史：视频来自 localStorage（watchHistory），漫画来自后端 /api/comics/history
export async function fetchHistory(): Promise<MediaItem[]> {
  const videoItems: MediaItem[] = []
  try {
    const stored = localStorage.getItem('watchHistory')
    if (stored) {
      const arr = JSON.parse(stored) as any[]
      for (const v of arr) {
        const dur = v.duration || 0
        videoItems.push({
          type: 'video',
          hash: v.hash,
          title: v.title,
          cover: v.thumbnail || '',
          thumbnail: v.thumbnail,
          duration: dur,
          progress: dur > 0 && v.progress ? v.progress / dur : 0,
          date: v.watched_at,
          raw: v
        })
      }
    }
  } catch (e) {
    console.error('读取视频历史失败:', e)
  }
  const c = (await comicApi.getHistory()) as any
  const comicItems: MediaItem[] =
    c?.success && Array.isArray(c.comics) ? c.comics.map(normalizeComic) : []
  return sortByDateDesc([...videoItems, ...comicItems])
}
