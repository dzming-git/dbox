// text 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const textApi = {
  list: (params?: { library_id?: number; search?: string }) => api.get('/api/texts', { params }),
  get: (id: number) => api.get(`/api/texts/${id}`),
  create: (data: { title: string; body?: string; summary?: string; location?: string; library_id?: number }) =>
    api.post('/api/texts', data),
  update: (id: number, data: any) => api.put(`/api/texts/${id}`, data),
  remove: (id: number) => api.delete(`/api/texts/${id}`),
}
