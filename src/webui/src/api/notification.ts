// 用户通知 API（通知中心：订阅事件/下载完成等统一展现层）
import api from './client'

export const notificationApi = {
  list: (params?: { limit?: number; offset?: number; unread_only?: boolean }) => {
    const p: Record<string, any> = {}
    if (params?.limit != null) p.limit = params.limit
    if (params?.offset != null) p.offset = params.offset
    if (params?.unread_only) p.unread_only = 1
    return api.get('/api/notifications', { params: p })
  },
  markRead: (id: number) => api.post(`/api/notifications/${id}/read`),
  markAllRead: () => api.post('/api/notifications/read-all'),
}
