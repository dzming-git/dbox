// config 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const configApi = {
  getConfig: () => api.get('/api/config'),
  updateConfig: (config: Record<string, unknown>) =>
    api.put('/api/config', config)
}
