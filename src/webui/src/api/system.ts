// 系统与服务管理相关 API
import api from './client'

export const systemApi = {
  getStatus: (params?: Record<string, unknown>) => api.get('/api/system/status', { params }),
  getServices: () => api.get('/api/services/status'),
  getService: (name: string) => api.get(`/api/service/${name}/status`),
  restartService: (name: string) => api.post(`/api/service/${name}/restart`),
  stopService: (name: string) => api.post(`/api/service/${name}/stop`),
  startService: (name: string) => api.post(`/api/service/${name}/start`),
  shutdown: (data?: Record<string, unknown>) => api.post('/api/system/shutdown', data || {}),
  cancelShutdown: () => api.post('/api/system/shutdown/cancel', {}),
  getSettings: () => api.get('/api/settings'),
  updateSetting: (scope: string, key: string, value: unknown) =>
    api.post('/api/settings', { scope, key, value }),
  getConfig: () => api.get('/api/config'),
  updateConfig: (config: Record<string, unknown>) => api.post('/api/config', config),
  getLog: (params?: Record<string, unknown>) => api.get('/api/log', { params }),
  getScanTasks: () => api.get('/api/scan/tasks'),
  sendCommand: (service: string, command: string) =>
    api.post(`/api/service/${service}/command`, { command })
}

export const serviceManageApi = {
  getServices: () => api.get('/api/admin/services'),
  getStatus: (name: string) => api.get(`/api/admin/services/${name}/status`),
  restart: (name: string) => api.post(`/api/admin/services/${name}/restart`),
  stop: (name: string) => api.post(`/api/admin/services/${name}/stop`),
  start: (name: string) => api.post(`/api/admin/services/${name}/start`),
  getLogs: (name: string, params?: Record<string, unknown>) =>
    api.get(`/api/admin/services/${name}/logs`, { params }),
  getConfig: () => api.get('/api/admin/services/config'),
  updateConfig: (data: Record<string, unknown>) => api.post('/api/admin/services/config', data)
}
