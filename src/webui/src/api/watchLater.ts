// watchLater 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const watchLaterApi = {
  list: () => api.get('/api/watch-later'),
  add: (item: { type: string; id: string; title?: string; thumbnail?: string }) =>
    api.post('/api/watch-later', item),
  remove: (type: string, id: string) => api.delete(`/api/watch-later/${type}/${id}`),
  clear: () => api.delete('/api/watch-later'),
}
