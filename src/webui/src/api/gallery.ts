// 图集（gallery）相关 API
import api from './client'

export const galleryApi = {
  getGalleries: (params?: Record<string, unknown>) => api.get('/api/galleries', { params }),
  getGallery: (hash: string) => api.get(`/api/gallery/${hash}`),
  getPages: (hash: string, params?: Record<string, unknown>) =>
    api.get(`/api/gallery/${hash}/pages`, { params }),
  update: (hash: string, data: Record<string, unknown>) => api.post(`/api/gallery/${hash}/update`, data),
  // 设置图集标签（同 setVideoTags 规则）
  setTags: (hash: string, tags: Array<string | { path: string; qualifiers?: string[] }>) =>
    api.post(`/api/gallery/${hash}/tags`, { tags }),
  like: (hash: string) => api.post(`/api/gallery/${hash}/like`),
  favorite: (hash: string) => api.post(`/api/gallery/${hash}/favorite`),
  dislike: (hash: string) => api.post(`/api/gallery/${hash}/dislike`),
  delete: (hash: string, deleteFile = false) =>
    api.delete(`/api/gallery/${hash}`, { data: { delete_file: deleteFile } }),
  scan: (params?: Record<string, unknown>) => api.post('/api/scan/galleries', params || {})
}
