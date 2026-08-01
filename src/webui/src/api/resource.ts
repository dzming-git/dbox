// resource 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const resourceApi = {
  pool: (params?: { mode?: string; library_id?: number; kind?: string; search?: string }) =>
    api.get('/api/resource-index', { params }),
  setModes: (id: number, data: { modes: string[]; collection_id?: number }) =>
    api.post(`/api/resource-index/${id}/modes`, data),
  collections: (mode?: string) => api.get('/api/mode-collections', { params: mode ? { mode } : {} }),
  createCollection: (data: { name: string; mode: string; library_id?: number }) =>
    api.post('/api/mode-collections', data),
  modes: () => api.get('/api/modes'),
  setHidden: (id: number, hidden: boolean) =>
    api.patch(`/api/resource-index/${id}/hidden`, { hidden }),
}
