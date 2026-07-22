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
  getVideos: (params?: { limit?: number; offset?: number; tag_id?: number; library_id?: number; search?: string; sort?: string; order?: string; exclude_disliked?: string }) =>
    api.get('/api/videos', { params }),

  // 获取当前用户可访问的资源库列表（用于筛选）
  getLibraries: () =>
    api.get('/api/user/libraries'),
  
  getVideo: (hash: string) =>
    api.get(`/api/video/${hash}`),
  
  likeVideo: (hash: string) =>
    api.post(`/api/video/${hash}/like`),
  
  favoriteVideo: (hash: string) =>
    api.post(`/api/video/${hash}/favorite`),

  dislikeVideo: (hash: string) =>
    api.post(`/api/video/${hash}/dislike`),

  // 获取当前用户的收藏列表（以后端为准）
  getFavorites: () =>
    api.get('/api/favorites'),
  getLikes: () =>
    api.get('/api/likes'),
  getDisliked: () =>
    api.get('/api/disliked'),
  // 批量互动（点赞/收藏/不喜欢）
  batchInteract: (hashes: string[], action: 'like' | 'favorite' | 'dislike') =>
    api.post('/api/videos/batch-interact', { hashes, action }),

  // 按 hash 列表获取视频概要（继续观看等本地历史重建用）
  getVideosByHashes: (hashes: string[]) =>
    api.post('/api/videos/by-hashes', { hashes }),
  // 统计概览
  getStats: () =>
    api.get('/api/stats/overview'),

  // 收藏夹分组
  getCollections: () => api.get('/api/favorite-collections'),
  createCollection: (name: string) => api.post('/api/favorite-collections', { name }),
  deleteCollection: (id: number) => api.delete(`/api/favorite-collections/${id}`),
  getCollectionVideos: (id: number) => api.get(`/api/favorite-collections/${id}/videos`),
  addToCollection: (id: number, type: 'video' | 'comic', hash: string) =>
    api.post(`/api/favorite-collections/${id}/videos`, { type, hash }),
  removeFromCollection: (id: number, type: 'video' | 'comic', hash: string) =>
    api.delete(`/api/favorite-collections/${id}/videos`, { data: { type, hash } }),

  deleteVideo: (hash: string, deleteFile = false) =>
    api.delete(`/api/video/${hash}`, { data: { delete_file: deleteFile } }),
  
  updateVideo: (hash: string, data: Record<string, unknown>) =>
    api.post(`/api/videos/${hash}/update`, data),

  // 设置视频标签（整体替换，传空数组即清空；接受层级路径数组如 ['/动物/狗']）
  setVideoTags: (hash: string, tags: string[]) =>
    api.post(`/api/video/${hash}/tags`, { tags }),
  
  scanVideos: () =>
    api.post('/api/scan', {}),
  
  getStatus: () =>
    api.get('/api/status')
}

// 合集模块（独立于收藏夹）：视频+漫画通用、支持排序与多归属、反向查询
export const collectionSetApi = {
  getCollections: () => api.get('/api/collections'),
  createCollection: (data: { name: string; description?: string; is_public?: boolean }) =>
    api.post('/api/collections', data),
  getCollection: (id: number) => api.get(`/api/collections/${id}`),
  updateCollection: (id: number, data: any) => api.put(`/api/collections/${id}`, data),
  deleteCollection: (id: number) => api.delete(`/api/collections/${id}`),
  getItems: (id: number) => api.get(`/api/collections/${id}/items`),
  addItem: (id: number, data: { item_type: 'video' | 'comic'; item_hash: string; position?: number }) =>
    api.post(`/api/collections/${id}/items`, data),
  reorderItems: (id: number, orderedIds: number[]) =>
    api.post(`/api/collections/${id}/items/reorder`, { ordered_ids: orderedIds }),
  removeItem: (id: number, itemId: number) =>
    api.delete(`/api/collections/${id}/items/${itemId}`),
  getByItem: (itemType: 'video' | 'comic', itemHash: string) =>
    api.get('/api/collections/by-item', { params: { item_type: itemType, item_hash: itemHash } }),
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

  // 删除缩略图
  delete: (hash: string) =>
    axios.delete(`${THUMB_BASE}/api/thumbnail/${hash}`),

  // 重新生成缩略图（管理后台使用）
  regenerate: (hash: string) =>
    axios.post(`${THUMB_BASE}/api/thumbnail/regenerate/${hash}`)
}

// 健康检查
export const healthApi = {
  check: () => api.get('/health'),
  checkThumbnail: () =>
    axios.get(`${THUMB_BASE}/health`)
}

// 资源库管理 API
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

  // 一键扫描所有资源库（异步）
  scanAllLibraries: () => api.post(`/api/admin/libraries/scan-all`, {}),
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

// 系统日志 API
export const logApi = {
  // 获取系统日志
  getLogs: (params: { type?: string; page?: number; limit?: number }) =>
    api.get('/api/admin/logs', { params })
}

// 缩略图管理 API
export const thumbnailManageApi = {
  // 获取缩略图配置和统计
  getConfig: () => api.get('/api/admin/thumbnail/config'),

  // 更新缩略图配置
  updateConfig: (config: {
    auto_generate?: boolean
    max_workers?: number
    task_interval?: number
    auto_generate_interval?: number
  }) => api.post('/api/admin/thumbnail/config', config),

  // 手动触发批量生成缺失缩略图
  generateMissing: () => api.post('/api/admin/thumbnail/generate-missing'),

  // 获取自动生成状态
  getAutoStatus: () => api.get('/api/admin/thumbnail/auto-generate/status'),

  // 停止自动生成
  stopAuto: () => api.post('/api/admin/thumbnail/auto-generate/stop')
}

// 服务管理 API
export const serviceManageApi = {
  // 获取所有 dplayer 服务的状态
  getServices: () => api.get('/api/admin/services'),

  // 控制服务（start/stop/restart）
  control: (serviceName: string, action: 'start' | 'stop' | 'restart') =>
    api.post(`/api/admin/services/${serviceName}/control`, { action })
}

// 漫画模式 API
export const comicApi = {
  // 列表 / 筛选 / 排序 / 分页
  getComics: (params?: {
    library_id?: number
    search?: string
    sort?: string
    order?: string
    only_favorited?: boolean
    only_liked?: boolean
    exclude_disliked?: string
    continue?: boolean
    limit?: number
    offset?: number
  }) => api.get('/api/comics', { params }),

  // 详情（含全部页面）
  getComic: (hash: string) =>
    api.get(`/api/comic/${hash}`),

  // 点赞 / 收藏 / 不喜欢
  interact: (hash: string, type: 'like' | 'favorite' | 'dislike') =>
    api.post(`/api/comic/${hash}/${type}`),

  // 阅读进度
  getProgress: (hash: string) =>
    api.get(`/api/comic/${hash}/progress`),
  saveProgress: (hash: string, page: number, progress: number) =>
    api.post(`/api/comic/${hash}/progress`, { page, progress }),

  // 我的漫画列表（与视频的 /api/favorites|likes|disliked|history 对齐，地位等同）
  getFavorites: () => api.get('/api/comics/favorites'),
  getLikes: () => api.get('/api/comics/likes'),
  getDisliked: () => api.get('/api/comics/disliked'),
  getHistory: () => api.get('/api/comics/history'),

  // 管理员：扫描库的漫画
  scan: (libraryId: number) =>
    api.post(`/api/admin/libraries/${libraryId}/scan-comics`, {}),
  scanStatus: (libraryId: number) =>
    api.get(`/api/admin/libraries/${libraryId}/comic-scan-status`),

  // 标签（复用主应用 tags 表，对齐视频标签体系）
  getComicTags: (params?: { tree?: boolean }) => api.get('/api/comics/tags', { params }),
  // 更新漫画信息（标题、所属资源库）
  updateComic: (hash: string, data: { title?: string; library_id?: number | null }) =>
    api.post(`/api/comic/${hash}/update`, data),
  getComicTagsByHash: (hash: string) => api.get(`/api/comic/${hash}/tags`),
  setComicTags: (hash: string, tags: string[]) => api.post(`/api/comic/${hash}/tags`, { tags }),
  removeComicTag: (hash: string, tagId: number) =>
    api.delete(`/api/comic/${hash}/tags`, { data: { tag_id: tagId } }),

  // 合集（播放列表，对齐视频 Playlist）
  getPlaylists: () => api.get('/api/comic-playlists'),
  createPlaylist: (data: { name: string; description?: string; is_public?: boolean }) =>
    api.post('/api/comic-playlists', data),
  getPlaylist: (id: number) => api.get(`/api/comic-playlists/${id}`),
  updatePlaylist: (id: number, data: any) => api.put(`/api/comic-playlists/${id}`, data),
  deletePlaylist: (id: number) => api.delete(`/api/comic-playlists/${id}`),
  addToPlaylist: (id: number, hash: string) => api.post(`/api/comic-playlists/${id}/comics`, { hash }),
  removeFromPlaylist: (id: number, hash: string) => api.delete(`/api/comic-playlists/${id}/comics/${hash}`),
  reorderPlaylist: (id: number, order: string[]) => api.put(`/api/comic-playlists/${id}/comics/reorder`, { order }),
}

export default api
