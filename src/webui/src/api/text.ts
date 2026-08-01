// 文本（text）相关 API
import api from './client'

export const textApi = {
  getTexts: (params?: Record<string, unknown>) => api.get('/api/texts', { params }),
  getText: (id: number) => api.get(`/api/texts/${id}`),
  createText: (data: Record<string, unknown>) => api.post('/api/texts', data),
  updateText: (id: number, data: Record<string, unknown>) => api.put(`/api/texts/${id}`, data),
  deleteText: (id: number) => api.delete(`/api/texts/${id}`),
  like: (id: number) => api.post(`/api/texts/${id}/like`),
  favorite: (id: number) => api.post(`/api/texts/${id}/favorite`)
}
