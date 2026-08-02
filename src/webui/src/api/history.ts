// 观看历史 API（视频/图集，后端为唯一数据源，取代 localStorage 分散记录）
import api from './client'

export const historyApi = {
  // 获取观看历史列表
  getHistory: () =>
    api.get('/api/history'),

  // 记录/更新观看进度（type: video/gallery, id: hash, progress: 0~1, duration: 秒）
  addHistory: (type: 'video' | 'gallery', id: string, progress = 0, duration = 0, extra?: { title?: string; thumbnail?: string }) =>
    api.post('/api/history', { type, id, progress, duration, ...extra }),

  // 删除单条历史
  removeHistory: (type: 'video' | 'gallery', id: string) =>
    api.delete(`/api/history/${type}/${id}`),

  // 清空全部历史
  clearHistory: () =>
    api.delete('/api/history'),
}
