// collectionSet 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const collectionSetApi = {
  getCollections: () => api.get('/api/collections'),
  createCollection: (data: { name: string; description?: string; is_public?: boolean }) =>
    api.post('/api/collections', data),
  getCollection: (id: number) => api.get(`/api/collections/${id}`),
  updateCollection: (id: number, data: any) => api.put(`/api/collections/${id}`, data),
  deleteCollection: (id: number) => api.delete(`/api/collections/${id}`),
  getItems: (id: number) => api.get(`/api/collections/${id}/items`),
  addItem: (id: number, data: { item_type: 'video' | 'gallery'; item_hash: string; position?: number }) =>
    api.post(`/api/collections/${id}/items`, data),
  reorderItems: (id: number, orderedIds: number[]) =>
    api.post(`/api/collections/${id}/items/reorder`, { ordered_ids: orderedIds }),
  removeItem: (id: number, itemId: number) =>
    api.delete(`/api/collections/${id}/items/${itemId}`),
  getByItem: (itemType: 'video' | 'gallery', itemHash: string) =>
    api.get('/api/collections/by-item', { params: { item_type: itemType, item_hash: itemHash } }),
}
