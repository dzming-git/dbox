// library 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

export const libraryApi = {
  // 获取所有资源库列表
  getLibraries: () => api.get('/api/admin/libraries'),

  // 创建资源库
  createLibrary: (data: { name: string; description?: string; db_file: string; config?: object }) =>
    api.post('/api/admin/libraries', data),

  // 获取资源库详情
  getLibrary: (id: number) => api.get(`/api/admin/libraries/${id}`),

  // 更新资源库
  updateLibrary: (id: number, data: { name?: string; description?: string; is_active?: boolean; config?: object }) =>
    api.put(`/api/admin/libraries/${id}`, data),

  // 删除资源库
  deleteLibrary: (id: number) => api.delete(`/api/admin/libraries/${id}`),

  // 获取资源库权限列表
  getLibraryPermissions: (libraryId: number) => api.get(`/api/admin/libraries/${libraryId}/permissions`),

  // 添加用户权限
  addLibraryPermission: (libraryId: number, data: { user_id?: number; group_id?: number; role: string; access_level: string; permissions?: string[] }) =>
    api.post(`/api/admin/libraries/${libraryId}/permissions`, data),

  // 更新用户权限
  updateLibraryPermission: (libraryId: number, permId: number, data: { role?: string; access_level?: string; permissions?: string[] }) =>
    api.put(`/api/admin/libraries/${libraryId}/permissions/${permId}`, data),

  // 删除用户权限
  deleteLibraryPermission: (libraryId: number, permId: number) =>
    api.delete(`/api/admin/libraries/${libraryId}/permissions/${permId}`),

  // 获取用户可访问的资源库
  getUserLibraries: () => api.get('/api/user/libraries'),

  // 切换当前资源库
  switchLibrary: (libraryId: number) => api.post('/api/user/libraries/switch', { library_id: libraryId }),

  // 启动扫描（异步）
  scanLibrary: (libraryId: number) => api.post(`/api/admin/libraries/${libraryId}/scan`, {}),

  // 一键同步所有资源库（异步，支持模式：incremental/verify/full）
  scanAllLibraries: (data?: { mode?: string }) => api.post(`/api/admin/libraries/scan-all`, data || {}),
  // 获取全量扫描进度
  getScanAllStatus: () => api.get(`/api/admin/libraries/scan-all/status`),

  // 获取用户组列表
  getUserGroups: () => api.get('/api/admin/user-groups'),

  // 创建用户组
  createUserGroup: (data: { name: string; description?: string }) =>
    api.post('/api/admin/user-groups', data),

  // 删除用户组
  deleteUserGroup: (groupId: number) => api.delete(`/api/admin/user-groups/${groupId}`),

  // 添加用户到用户组
  addUserToGroup: (groupId: number, userId: number) =>
    api.post(`/api/admin/user-groups/${groupId}/members`, { user_id: userId }),

  // 从用户组移除用户
  removeUserFromGroup: (groupId: number, userId: number) =>
    api.delete(`/api/admin/user-groups/${groupId}/members/${userId}`),

  // 获取审计日志
  getAuditLogs: (libraryId: number) => api.get(`/api/admin/libraries/${libraryId}/audit-logs`),

  // 获取扫描进度（轮询）
  getScanProgress: (libraryId: number) => api.get(`/api/admin/libraries/${libraryId}/scan-status`),
}

export const logApi = {
  // 获取系统日志
  getLogs: (params: { type?: string; page?: number; limit?: number }) =>
    api.get('/api/admin/logs', { params })
}

export const eventApi = {
  // 获取事件监听器日志（反馈事件处理日志）
  getLog: (params: { tail?: number; page?: number; limit?: number }) =>
    api.get('/api/admin/event-log', { params }),
  // 获取事件监听器配置
  getConfig: () => api.get('/api/admin/event-listener/config'),
  // 保存事件监听器配置（自动重启服务生效）
  saveConfig: (config: any) => api.put('/api/admin/event-listener/config', { config }),
  // 仅重启监听器服务
  restart: () => api.post('/api/admin/event-listener/restart'),
}
