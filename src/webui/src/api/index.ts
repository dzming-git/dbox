import axios from 'axios'

// 根据环境自动选择API地址
// 开发环境使用代理（留空，让 Vite 代理处理），生产环境使用相对路径（同域名）
const isDev = import.meta.env.DEV
const API_BASE = ''  // 统一使用相对路径，开发时由 Vite 代理处理

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  withCredentials: true,
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

// ---- 401 自动刷新 access_token，避免登录态被无故踢出 ----
// 用 refresh_token 静默换取新 access_token；仅在刷新也失败时才清理并跳登录。
let isRefreshing = false
let pendingQueue: Array<(token: string | null) => void> = []

function subscribeTokenRefresh(cb: (token: string | null) => void) {
  pendingQueue.push(cb)
}
function onRefreshed(token: string | null) {
  pendingQueue.forEach(cb => cb(token))
  pendingQueue = []
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return null
  try {
    // 注意：用裸 axios 调用，不经过 api 拦截器，避免对刷新接口自身递归触发刷新
    const resp = await axios.post('/api/v2/auth/refresh', { refresh_token: refreshToken }, {
      headers: { 'Content-Type': 'application/json' }
    })
    const data = resp.data
    if (data && data.success && data.data && data.data.access_token) {
      const newToken = data.data.access_token
      localStorage.setItem('token', newToken)
      try {
        const { useUserStore } = await import('../stores/userStore')
        useUserStore().setTokens(newToken, data.data.refresh_token)
      } catch {
        // 忽略 store 未就绪的情况，token 已写入 localStorage
      }
      return newToken
    }
    return null
  } catch {
    return null
  }
}

async function clearAuthAndRedirect() {
  localStorage.removeItem('token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user')
  try {
    const { useUserStore } = await import('../stores/userStore')
    useUserStore().logout()
  } catch {
    // ignore
  }
  const currentPath = window.location.pathname + window.location.search
  if (currentPath !== '/login') {
    window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`
  }
}

// 响应拦截器
api.interceptors.response.use(
  response => response.data,
  async error => {
    const original = error.config as any
    const status = error.response?.status
    if (status === 401 && original && !original._retry) {
      const url: string = original.url || ''
      // 登录/刷新接口本身返回 401：直接清理并跳登录（不再重试，避免死循环）
      if (url.includes('/api/v2/auth/login') || url.includes('/api/v2/auth/refresh')) {
        await clearAuthAndRedirect()
        return Promise.reject(error)
      }
      // 已有刷新在进行：排队，等刷新完成后用新 token 重试
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          subscribeTokenRefresh(token => {
            if (token) {
              original._retry = true
              original.headers.Authorization = `Bearer ${token}`
              resolve(api(original))
            } else {
              reject(error)
            }
          })
        })
      }
      original._retry = true
      isRefreshing = true
      try {
        const newToken = await refreshAccessToken()
        if (newToken) {
          onRefreshed(newToken)
          original.headers.Authorization = `Bearer ${newToken}`
          return api(original)
        }
        onRefreshed(null)
        await clearAuthAndRedirect()
      } finally {
        isRefreshing = false
      }
      return Promise.reject(error)
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
  addToCollection: (id: number, type: 'video' | 'gallery', hash: string) =>
    api.post(`/api/favorite-collections/${id}/videos`, { type, hash }),
  removeFromCollection: (id: number, type: 'video' | 'gallery', hash: string) =>
    api.delete(`/api/favorite-collections/${id}/videos`, { data: { type, hash } }),

  deleteVideo: (hash: string, deleteFile = false) =>
    api.delete(`/api/video/${hash}`, { data: { delete_file: deleteFile } }),

  deleteGallery: (hash: string, deleteFile = false) =>
    api.delete(`/api/gallery/${hash}`, { data: { delete_file: deleteFile } }),

  // 回收站（管理员）
  getTrash: () => api.get('/api/admin/trash'),
  restoreTrash: (type: 'video' | 'gallery', hash: string) =>
    api.post('/api/admin/trash/restore', { type, hash }),
  purgeTrash: (type: 'video' | 'gallery', hash: string) =>
    api.post('/api/admin/trash/purge', { type, hash }),
  emptyTrash: () => api.post('/api/admin/trash/empty'),
  

  updateVideo: (hash: string, data: Record<string, unknown>) =>
    api.post(`/api/videos/${hash}/update`, data),

  // 设置视频标签（整体替换，传空数组即清空）。
  // 兼容两种格式：字符串路径 "/猫" 或对象 {"path":"/猫","qualifiers":["白","长毛"]}
  setVideoTags: (hash: string, tags: Array<string | { path: string; qualifiers?: string[] }>) =>
    api.post(`/api/video/${hash}/tags`, { tags }),
  
  scanVideos: () =>
    api.post('/api/scan', {}),
  
  getStatus: () =>
    api.get('/api/status')
}

// 合集模块（独立于收藏夹）：视频+图集通用、支持排序与多归属、反向查询
export const collectionSetApi = {
  getCollections: () => api.get('/api/collections'),
  createCollection: (data: { name: string; description?: string; is_public?: boolean }) =>
    api.post('/api/collections', data),
  getCollection: (id: number) => api.get(`/api/collections/${id}`),
  updateCollection: (id: number, data: any) => api.put(`/api/collections/${id}`, data),
  deleteCollection: (id: number) => api.delete(`/api/collections/${id}`),
  getItems: (id: number) => api.get(`/api/collections/${id}/items`),
  addItem: (id: number, data: { item_type: 'video' | 'gallery'; item_hash: string; position?: number }) =>
    api.post(`/api/collections/${id}/items`, data),
  reorderItems: (id: number, orderedIds: number[]) =>
    api.post(`/api/collections/${id}/items/reorder`, { ordered_ids: orderedIds }),
  removeItem: (id: number, itemId: number) =>
    api.delete(`/api/collections/${id}/items/${itemId}`),
  getByItem: (itemType: 'video' | 'gallery', itemHash: string) =>
    api.get('/api/collections/by-item', { params: { item_type: itemType, item_hash: itemHash } }),
}

// 标签相关API - 支持多级标签
export const tagApi = {
  // 获取标签列表 - 支持tree参数获取树形结构
  getTags: (params?: { tree?: boolean }) => api.get('/api/tags', { params }),
  
  // 获取所有标签（管理员用，不进行权限过滤）
  getAllTags: () => api.get('/api/tags/all'),
  
  // 创建标签 - 支持parent_id创建子标签，支持 qualifiers 补充项
  createTag: (name: string, category?: string, parentId?: number, qualifiers?: string[]) =>
    api.post('/api/tags', { name, category, parent_id: parentId, qualifiers }),
  
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

// 图集模式 API
export const galleryApi = {
  // 列表 / 筛选 / 排序 / 分页
  getGallerys: (params?: {
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
  }) => api.get('/api/galleries', { params }),

  // 详情（含全部页面）
  getGallery: (hash: string) =>
    api.get(`/api/gallery/${hash}`),

  // 删除（移入回收站；管理员传 deleteFile=true 可永久删除）
  deleteGallery: (hash: string, deleteFile = false) =>
    api.delete(`/api/gallery/${hash}`, { data: { delete_file: deleteFile } }),

  // 重新加载图集资源（从磁盘重新同步页面/封面，图片被替换/增删后强制刷新）
  reloadGallery: (hash: string) =>
    api.post(`/api/gallery/${hash}/reload`),

  // 点赞 / 收藏 / 不喜欢
  interact: (hash: string, type: 'like' | 'favorite' | 'dislike') =>
    api.post(`/api/gallery/${hash}/${type}`),

  // 阅读进度
    getProgress: (hash: string) =>
      api.get(`/api/gallery/${hash}/progress`),
    saveProgress: (hash: string, page: number, progress: number) =>
      api.post(`/api/gallery/${hash}/progress`, { page, progress }),
    setContinue: (hash: string, add: boolean) =>
      api.post(`/api/gallery/${hash}/continue`, { add }),

  // 我的图集列表（与视频的 /api/favorites|likes|disliked|history 对齐，地位等同）
  getFavorites: () => api.get('/api/galleries/favorites'),
  getLikes: () => api.get('/api/galleries/likes'),
  getDisliked: () => api.get('/api/galleries/disliked'),
  getHistory: () => api.get('/api/galleries/history'),

  // 管理员：扫描库的图集
  scan: (libraryId: number) =>
    api.post(`/api/admin/libraries/${libraryId}/scan-galleries`, {}),
  scanStatus: (libraryId: number) =>
    api.get(`/api/admin/libraries/${libraryId}/gallery-scan-status`),

  // 标签（复用主应用 tags 表，对齐视频标签体系）
  getGalleryTags: (params?: { tree?: boolean }) => api.get('/api/galleries/tags', { params }),
  // 更新图集信息（标题、所属资源库）
  updateGallery: (hash: string, data: { title?: string; library_id?: number | null }) =>
    api.post(`/api/gallery/${hash}/update`, data),
  getGalleryTagsByHash: (hash: string) => api.get(`/api/gallery/${hash}/tags`),
  setGalleryTags: (hash: string, tags: string[]) => api.post(`/api/gallery/${hash}/tags`, { tags }),
  removeGalleryTag: (hash: string, tagId: number) =>
    api.delete(`/api/gallery/${hash}/tags`, { data: { tag_id: tagId } }),

  // 合集（播放列表，对齐视频 Playlist）
  getPlaylists: () => api.get('/api/gallery-playlists'),
  createPlaylist: (data: { name: string; description?: string; is_public?: boolean }) =>
    api.post('/api/gallery-playlists', data),
  getPlaylist: (id: number) => api.get(`/api/gallery-playlists/${id}`),
  updatePlaylist: (id: number, data: any) => api.put(`/api/gallery-playlists/${id}`, data),
  deletePlaylist: (id: number) => api.delete(`/api/gallery-playlists/${id}`),
  addToPlaylist: (id: number, hash: string) => api.post(`/api/gallery-playlists/${id}/galleries`, { hash }),
  removeFromPlaylist: (id: number, hash: string) => api.delete(`/api/gallery-playlists/${id}/galleries/${hash}`),
  reorderPlaylist: (id: number, order: string[]) => api.put(`/api/gallery-playlists/${id}/galleries/reorder`, { order }),
}

// 系统控制 API（电脑关机）
export const systemApi = {
  // action: immediate(立即) / scheduled(定时，需 minutes) / after_tasks(任务全部结束后)
  shutdown: (action: 'immediate' | 'scheduled' | 'after_tasks', minutes?: number) =>
    api.post('/api/system/shutdown', { action, minutes }),
  cancelShutdown: () =>
    api.post('/api/system/shutdown/cancel')
}

// 帖子（Post）API：帖子通过资源索引表自由引用视频/图片集（图集）/未来文本
export const postApi = {
  // 列表（仅未删除）
  list: (params?: { library_id?: number }) =>
    api.get('/api/posts', { params }),
  get: (id: number) =>
    api.get(`/api/posts/${id}`),
  // 创建：refs 为 [{ resource_index_id, note? }]
  create: (data: { title: string; content: string; library_id?: number; refs: Array<{ resource_index_id: number; note?: string }> }) =>
    api.post('/api/posts', data),
  update: (id: number, data: any) =>
    api.put(`/api/posts/${id}`, data),
  remove: (id: number, data?: { delete_resources?: boolean; resource_index_ids?: number[] }) =>
    api.delete(`/api/posts/${id}`, data ? { data } : undefined),
}

// 统一资源池：跨模式选择资源（视频 / 图片集 / 文本），供帖子引用选择器复用
export const resourceApi = {
  pool: (params?: { mode?: string; library_id?: number; kind?: string; search?: string }) =>
    api.get('/api/resource-index', { params }),
  setModes: (id: number, data: { modes: string[]; collection_id?: number }) =>
    api.post(`/api/resource-index/${id}/modes`, data),
  collections: (mode?: string) => api.get('/api/mode-collections', { params: mode ? { mode } : {} }),
  createCollection: (data: { name: string; mode: string; library_id?: number }) =>
    api.post('/api/mode-collections', data),
  modes: () => api.get('/api/modes'),
  setHidden: (id: number, hidden: boolean) =>
    api.patch(`/api/resource-index/${id}/hidden`, { hidden }),
}

// 文本模式（未来内容管理）
export const textApi = {
  list: (params?: { library_id?: number; search?: string }) => api.get('/api/texts', { params }),
  get: (id: number) => api.get(`/api/texts/${id}`),
  create: (data: { title: string; body?: string; summary?: string; location?: string; library_id?: number }) =>
    api.post('/api/texts', data),
  update: (id: number, data: any) => api.put(`/api/texts/${id}`, data),
  remove: (id: number) => api.delete(`/api/texts/${id}`),
}

export default api
