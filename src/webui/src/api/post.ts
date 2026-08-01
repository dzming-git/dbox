// post 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const postApi = {
  // 列表（仅未删除）
  list: (params?: { library_id?: number }) =>
    api.get('/api/posts', { params }),
  get: (id: number) =>
    api.get(`/api/posts/${id}`),
  // 创建：refs 为 [{ resource_index_id, note? }]
  create: (data: { title: string; content: string; library_id?: number; refs: Array<{ resource_index_id: number; note?: string }> }) =>
    api.post('/api/posts', data),
  update: (id: number, data: any) =>
    api.put(`/api/posts/${id}`, data),
  remove: (id: number, data?: { delete_resources?: boolean; resource_index_ids?: number[] }) =>
    api.delete(`/api/posts/${id}`, data ? { data } : undefined),
}
