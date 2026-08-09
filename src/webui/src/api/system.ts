// system 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const serviceManageApi = {
  // 获取所有 dbox 服务的状态
  getServices: () => api.get('/api/admin/services'),

  // 控制服务（start/stop/restart）
  control: (serviceName: string, action: 'start' | 'stop' | 'restart') =>
    api.post(`/api/admin/services/${serviceName}/control`, { action })
}

export const systemApi = {
  // 看门狗汇总的整体健康状态（各服务总线 ping + 自动重启 + 告警）
  getHealth: () => api.get('/api/admin/health'),
  // action: immediate(立即) / scheduled(定时，需 minutes) / after_tasks(任务全部结束后)
  shutdown: (action: 'immediate' | 'scheduled' | 'after_tasks', minutes?: number) =>
    api.post('/api/system/shutdown', { action, minutes }),
  cancelShutdown: () =>
    api.post('/api/system/shutdown/cancel')
}
