// 互动数据管理 API
import api from './client'

export const interactionApi = {
  // 清空当前用户全部互动数据（收藏/点赞/踩/历史/稍后）
  clearAll: () => api.delete('/api/interactions/all'),
}
