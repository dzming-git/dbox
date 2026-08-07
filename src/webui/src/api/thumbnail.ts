// thumbnail 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const thumbnailApi = {
  getThumbnail: (hash: string) =>
    `${API_BASE}/thumbnail/${hash}`,

  // 删除缩略图
  delete: (hash: string) =>
    axios.delete(`${API_BASE}/api/thumbnail/${hash}`),

  // 重新生成缩略图（管理后台使用）
  regenerate: (hash: string) =>
    axios.post(`${API_BASE}/api/thumbnail/regenerate/${hash}`)
}

export const healthApi = {
  check: () => api.get('/health'),
  checkThumbnail: () =>
    axios.get(`${API_BASE}/health`)
}

export const thumbnailManageApi = {
  // 获取缩略图配置和统计
  getConfig: () => api.get('/api/admin/thumbnail/config'),

  // 更新缩略图配置
  updateConfig: (config: {
    auto_generate?: boolean
    max_workers?: number
    task_interval?: number
    auto_generate_interval?: number
  }) => api.post('/api/admin/thumbnail/config', config),

  // 手动触发批量生成缺失缩略图
  generateMissing: () => api.post('/api/admin/thumbnail/generate-missing'),

  // 获取自动生成状态
  getAutoStatus: () => api.get('/api/admin/thumbnail/auto-generate/status'),

  // 停止自动生成
  stopAuto: () => api.post('/api/admin/thumbnail/auto-generate/stop')
}
