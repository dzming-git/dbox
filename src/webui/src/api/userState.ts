import api from './client'

/**
 * 跨设备用户状态（后端 /api/user-state/<ns>/<key>）。
 *
 * 保存的视图、插件状态等都可以落在这里：按 user/device/global 作用域存储，
 * union_by_id 策略适合「一个列表」类的状态（每条带 id 与 order）。
 * 只有登录用户可用。
 */
export const userStateApi = {
  list: (ns: string, keys?: string[]) =>
    api.get(`/api/user-state/${ns}`, { params: keys?.length ? { keys: keys.join(',') } : {} }),
  get: (ns: string, key: string) => api.get(`/api/user-state/${ns}/${key}`),
  put: (
    ns: string,
    key: string,
    value: any,
    opts?: { strategy?: 'lww' | 'max' | 'union_by_id'; scope?: 'user' | 'device'; cap?: number }
  ) => api.put(`/api/user-state/${ns}/${key}`, { value, ...(opts || {}) }),
  remove: (ns: string, key: string) => api.delete(`/api/user-state/${ns}/${key}`),
}
