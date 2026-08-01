// 资源索引（resource index）相关 API
import api from './client'

export const resourceApi = {
  // 资源池（视频/图集/文本等可被引用的资源索引）
  getResources: (params?: Record<string, unknown>) => api.get('/api/resource-index', { params }),
  getResource: (id: number) => api.get(`/api/resource-index/${id}`),
  setModes: (id: number, modes: string[], group?: string) =>
    api.post(`/api/resource-index/${id}/modes`, { modes, group }),
  repoint: (id: number, location: string) =>
    api.post(`/api/resource-index/${id}/repoint`, { location }),
  // 模式定义
  getModes: () => api.get('/api/modes'),
  // 模式集合（分组）
  getModeCollections: () => api.get('/api/mode-collections'),
  createModeCollection: (data: Record<string, unknown>) => api.post('/api/mode-collections', data),
  // 下载脚本入库后引用选择
  getResourcePool: (params?: Record<string, unknown>) => api.get('/api/resource-index', { params })
}
