// system 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const serviceManageApi = {
  // 获取所有 dbox 服务的状态
  getServices: () => api.get('/api/ext/service-ops/services'),

  // 控制服务（start/stop/restart）
  control: (serviceName: string, action: 'start' | 'stop' | 'restart') =>
    api.post(`/api/ext/service-ops/${serviceName}/control`, { action })
}

export const systemApi = {
  // 看门狗汇总的整体健康状态（服务运维面板插件）
  getHealth: () => api.get('/api/ext/service-ops/health')
}
