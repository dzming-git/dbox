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
}
