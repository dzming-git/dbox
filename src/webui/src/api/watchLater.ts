// 稍后观看相关 API
import api from './client'

export const watchLaterApi = {
  getWatchLater: (params?: Record<string, unknown>) => api.get('/api/watch-later', { params }),
  addWatchLater: (type: 'video' | 'gallery', hash: string) =>
    api.post('/api/watch-later', { type, hash }),
  removeWatchLater: (type: 'video' | 'gallery', hash: string) =>
    api.delete('/api/watch-later', { data: { type, hash } })
}
