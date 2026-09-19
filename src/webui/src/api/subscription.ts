// 订阅 API（用户关注来源：X 账号 / pixiv 画师等）
import api from './client'

export interface SubscriptionInput {
  sourceType: string
  sourceId: string
  sourceName?: string
  targetMode?: string
  libraryId?: number | null
  filters?: Record<string, any>
  enabled?: boolean
}

export const subscriptionApi = {
  list: () => api.get('/api/subscriptions'),
  create: (data: SubscriptionInput) => api.post('/api/subscriptions', data),
  update: (id: number, data: Partial<SubscriptionInput>) =>
    api.put(`/api/subscriptions/${id}`, data),
  remove: (id: number) => api.delete(`/api/subscriptions/${id}`),
  // 订阅缓存（轮询到的新内容，先缓存、再按需入库）
  cacheList: (params?: { source_type?: string; ingested?: string }) =>
    api.get('/api/subscription-cache', { params }),
  cacheIngest: (id: number) => api.post(`/api/subscription-cache/${id}/ingest`),
  cacheDismiss: (id: number) => api.delete(`/api/subscription-cache/${id}`),
  // 经扩展代理触发对应扩展下载（携带用户凭证，复用各扩展 /run 管线）
  runDownload: (sourceType: string, payload: any) =>
    api.post(`/api/ext/${sourceType}/run`, payload),
}
