// 配置相关 API
import api from './client'

export const configApi = {
  get: () => api.get('/api/config'),
  update: (config: Record<string, unknown>) => api.post('/api/config', config),
  getSettings: () => api.get('/api/settings'),
  updateSetting: (scope: string, key: string, value: unknown) =>
    api.post('/api/settings', { scope, key, value })
}
