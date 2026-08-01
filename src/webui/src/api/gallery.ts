// gallery 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

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
