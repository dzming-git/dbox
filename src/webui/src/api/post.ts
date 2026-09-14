// post 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

/** 帖子策展状态：草稿（仅自己可见）/ 已发布 */
export type PostStatus = 'draft' | 'published'

export const postApi = {
  // 列表：status 默认由后端取 published；mine=1 只看自己的
  list: (params?: {
    library_id?: number
    status?: PostStatus | 'all'
    mine?: 0 | 1
    search?: string
  }) => api.get('/api/posts', { params }),
  get: (id: number) => api.get(`/api/posts/${id}`),
  // 创建：refs 可选（不传就是一篇空草稿，之后再往里加引用）
  create: (data: {
    title: string
    content?: string
    library_id?: number
    status?: PostStatus
    refs?: Array<{ resource_index_id: number; note?: string }>
  }) => api.post('/api/posts', data),
  update: (
    id: number,
    data: {
      title?: string
      content?: string
      library_id?: number
      status?: PostStatus
      refs?: Array<{ resource_index_id: number; note?: string }>
    }
  ) => api.put(`/api/posts/${id}`, data),
  remove: (
    id: number,
    data?: { delete_resources?: boolean; resource_index_ids?: number[] }
  ) => api.delete(`/api/posts/${id}`, data ? { data } : undefined),
  // 追加一条引用（后端自动排到末尾）
  addRef: (
    id: number,
    data: {
      resource_index_id: number
      note?: string
    }
  ) => api.post(`/api/posts/${id}/refs`, data),
  removeRef: (id: number, refId: number) =>
    api.delete(`/api/posts/${id}/refs/${refId}`),
  // 重排引用：给出完整的新顺序（PostRef.id 数组）
  reorderRefs: (id: number, order: number[]) =>
    api.patch(`/api/posts/${id}/refs/order`, { order }),
}
