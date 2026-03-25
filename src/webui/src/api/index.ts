import axios from 'axios'

// 根据环境自动选择API地址
// 开发环境使用代理（留空，让 Vite 代理处理），生产环境使用相对路径（同域名）
const isDev = import.meta.env.DEV
const API_BASE = ''  // 统一使用相对路径，开发时由 Vite 代理处理

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
api.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

// 响应拦截器
api.interceptors.response.use(
  response => response.data,
  error => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token')
      // 获取当前路径，用于登录后跳转回来
      const currentPath = window.location.pathname + window.location.search
      const loginUrl = currentPath !== '/login' 
        ? `/login?redirect=${encodeURIComponent(currentPath)}`
        : '/login'
      window.location.href = loginUrl
    }
    return Promise.reject(error)
  }
)

// 视频相关API
export const videoApi = {
  getVideos: (params?: { limit?: number; offset?: number; tag_id?: number }) =>
    api.get('/api/videos', { params }),
  
  getVideo: (hash: string) =>
    api.get(`/api/video/${hash}`),
  
  likeVideo: (hash: string) =>
    api.post(`/api/video/${hash}/like`),
  
  favoriteVideo: (hash: string) =>
    api.post(`/api/video/${hash}/favorite`),
  
  deleteVideo: (hash: string, deleteFile = false) =>
    api.delete(`/api/video/${hash}`, { data: { delete_file: deleteFile } }),
  
  updateVideo: (hash: string, data: Record<string, unknown>) =>
    api.post(`/api/videos/${hash}/update`, data),
  
  scanVideos: () =>
    api.post('/api/scan'),
  
  getStatus: () =>
    api.get('/api/status')
}

// 标签相关API - 支持多级标签
export const tagApi = {
  // 获取标签列表 - 支持tree参数获取树形结构
  getTags: (params?: { tree?: boolean }) => api.get('/api/tags', { params }),
  
  // 获取所有标签（管理员用，不进行权限过滤）
  getAllTags: () => api.get('/api/tags/all'),
  
  // 创建标签 - 支持parent_id创建子标签
  createTag: (name: string, category?: string, parentId?: number) =>
    api.post('/api/tags', { name, category, parent_id: parentId }),
  
  // 更新标签 - 支持修改parent_id
  updateTag: (id: number, data: Record<string, unknown>) =>
    api.put(`/api/tags/${id}`, data),
  
  // 删除标签
  deleteTag: (id: number) =>
    api.delete(`/api/tags/${id}`),

  // 搜索标签 - 用于智能提示
  searchTags: (keyword: string, libraryId?: number) =>
    api.get('/api/tags/search', { params: { q: keyword, library_id: libraryId } })
}

// 配置相关API
export const configApi = {
  getConfig: () => api.get('/api/config'),
  updateConfig: (config: Record<string, unknown>) =>
    api.put('/api/config', config)
}

// 缩略图API
const THUMB_BASE = ''  // 统一使用相对路径，开发时由 Vite 代理处理

export const thumbnailApi = {
  getThumbnail: (hash: string) =>
    `${API_BASE}/thumbnail/${hash}`,

  generate: (videoPath: string, videoHash: string) =>
    axios.post(`${THUMB_BASE}/api/thumbnail/generate`, {
      video_path: videoPath,
      video_hash: videoHash
    }),

  // 查询缩略图状态
  getStatus: (hash: string) =>
    axios.get(`${THUMB_BASE}/api/thumbnail/status/${hash}`),

  // 删除缩略图
  delete: (hash: string) =>
    axios.delete(`${THUMB_BASE}/api/thumbnail/${hash}`),

  // 重新生成缩略图
  regenerate: (hash: string) =>
    axios.post(`${THUMB_BASE}/api/thumbnail/regenerate/${hash}`)
}

// 健康检查
export const healthApi = {
  check: () => api.get('/health'),
  checkThumbnail: () =>
    axios.get(`${THUMB_BASE}/health`)
}

// 视频库管理 API
export const libraryApi = {
  // 获取所有视频库列表
  getLibraries: () => api.get('/api/admin/libraries'),

  // 创建视频库
  createLibrary: (data: { name: string; description?: string; db_file: string; config?: object }) =>
    api.post('/api/admin/libraries', data),

  // 获取视频库详情
  getLibrary: (id: number) => api.get(`/api/admin/libraries/${id}`),

  // 更新视频库
  updateLibrary: (id: number, data: { name?: string; description?: string; is_active?: boolean; config?: object }) =>
    api.put(`/api/admin/libraries/${id}`, data),

  // 删除视频库
  deleteLibrary: (id: number) => api.delete(`/api/admin/libraries/${id}`),

  // 获取视频库权限列表
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

  // 获取用户可访问的视频库
  getUserLibraries: () => api.get('/api/user/libraries'),

  // 切换当前视频库
  switchLibrary: (libraryId: number) => api.post('/api/user/libraries/switch', { library_id: libraryId }),

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
  getAuditLogs: (libraryId: number) => api.get(`/api/admin/libraries/${libraryId}/audit-logs`)
}

export default api
