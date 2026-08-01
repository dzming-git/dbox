// 缩略图相关 API
import api from './client'

export const thumbnailApi = {
  getConfig: () => api.get('/api/thumbnail/config'),
  updateConfig: (config: Record<string, unknown>) => api.post('/api/thumbnail/config', config),
  testRemux: () => api.post('/api/gif/test-remux', {}),
  startAutoGenerate: () => api.post('/api/thumbnail/auto/generate', {}),
  getProgress: () => api.get('/api/thumbnail/progress'),
  generateForVideo: (hash: string) => api.post(`/api/thumbnail/generate/${hash}`),
  batchGenerate: (hashes: string[]) => api.post('/api/thumbnail/batch-generate', { hashes })
}

export const thumbnailManageApi = {
  getConfig: () => api.get('/api/admin/thumbnail/config'),
  updateConfig: (config: Record<string, unknown>) => api.post('/api/admin/thumbnail/config', config),
  getTasks: () => api.get('/api/admin/thumbnail/tasks'),
  getStatus: () => api.get('/api/admin/thumbnail/status'),
  start: () => api.post('/api/admin/thumbnail/start', {}),
  stop: () => api.post('/api/admin/thumbnail/stop', {}),
  regenerate: (hash: string) => api.post(`/api/admin/thumbnail/regenerate/${hash}`),
  batchRegenerate: (hashes: string[]) => api.post('/api/admin/thumbnail/batch-regenerate', { hashes })
}

export const healthApi = {
  check: () => api.get('/api/health'),
  checkDb: () => api.get('/api/health/db')
}
