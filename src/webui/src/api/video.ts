// video 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

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
