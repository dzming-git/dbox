// 收藏集（collection set）相关 API
import api from './client'

export const collectionSetApi = {
  create: () => api.get('/api/v1/collectionset/create'),
  getSaves: (id: string | number) => api.get(`/api/v1/collectionset/${id}/saves`),
  getLatest: () => api.get(`/api/v1/collectionset/latest`),
  save: (id: string | number, data: unknown) => api.post(`/api/v1/collectionset/${id}/save`, data),
  deleteSave: (id: string | number, saveId: string | number) =>
    api.delete(`/api/v1/collectionset/${id}/save/${saveId}`),
  delete: (id: string | number) => api.delete(`/api/v1/collectionset/${id}`)
}
