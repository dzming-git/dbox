import { api } from './index'

/** 审阅队列的问题类型 */
export type ReviewKind =
  | 'missing_file'
  | 'no_metadata'
  | 'no_cover'
  | 'untagged'
  | 'duplicate'

export interface ReviewItem {
  id: number
  hash: string
  title: string
  library_id: number | null
  duration: number | null
  file_size: number | null
  path: string | null
  reason: string
}

export interface ReviewSummary {
  success: boolean
  missing_file: number
  no_metadata: number
  no_cover: number
  untagged: number
  duplicate: number
  [key: string]: any
}

export const reviewApi = {
  // 各类问题的数量概览
  summary: () => api.get('/api/admin/review/summary'),
  // 某一类问题的条目列表
  items: (type: ReviewKind, limit = 50, offset = 0) =>
    api.get('/api/admin/review/items', { params: { type, limit, offset } }),
  // 批量处置：trash / remap / tag
  action: (data: {
    action: 'trash' | 'remap' | 'tag'
    ids?: number[]
    items?: { id: number; path: string }[]
    tag?: string
  }) => api.post('/api/admin/review/action', data),
  // 补齐缺失的时长与文件大小（后台任务）
  backfill: () => api.post('/api/admin/review/backfill'),
}
