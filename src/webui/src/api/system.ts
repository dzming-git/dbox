// system 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const serviceManageApi = {
  // 获取所有 dbox 服务的状态
  getServices: () => api.get('/api/ext/service-ops/services'),

  // 控制服务（start/stop/restart）
  control: (serviceName: string, action: 'start' | 'stop' | 'restart') =>
    api.post(`/api/ext/service-ops/${serviceName}/control`, { action }),

  // 重启所有非基础设施的 dbox 服务（模拟重启整机）。
  // 重启全部服务耗时较长，单独放宽超时，避免请求被默认 10s 超时误判为失败。
  restartAll: () => api.post('/api/ext/service-ops/restart-all', undefined, { timeout: 180000 })
}

export const systemApi = {
  // 看门狗汇总的整体健康状态（服务运维面板插件）
  getHealth: () => api.get('/api/ext/service-ops/health')
}
