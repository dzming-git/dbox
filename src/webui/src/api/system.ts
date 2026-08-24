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
  getHealth: () => api.get('/api/ext/service-ops/health'),
  // 关机（系统电源控制插件）：按 action 分发到对应端点
  shutdown: (action: 'immediate' | 'scheduled' | 'after_tasks', minutes?: number) => {
    if (action === 'immediate') return api.post('/api/ext/system-power/shutdown', { immediate: true })
    if (action === 'scheduled') return api.post('/api/ext/system-power/shutdown/scheduled', { minutes })
    return api.post('/api/ext/system-power/shutdown/after-tasks', { enable: true })
  },
  cancelShutdown: () =>
    api.post('/api/ext/system-power/shutdown/cancel')
}
