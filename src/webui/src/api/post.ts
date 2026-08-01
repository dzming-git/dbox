// 帖子（post）相关 API
import api from './client'

export const postApi = {
  getPosts: (params?: Record<string, unknown>) => api.get('/api/posts', { params }),
  getPost: (id: number) => api.get(`/api/posts/${id}`),
  createPost: (data: Record<string, unknown>) => api.post('/api/posts', data),
  updatePost: (id: number, data: Record<string, unknown>) => api.put(`/api/posts/${id}`, data),
  deletePost: (id: number) => api.delete(`/api/posts/${id}`),
  addRef: (id: number, resourceIndexId: number, meta?: Record<string, unknown>) =>
    api.post(`/api/posts/${id}/refs`, { resource_index_id: resourceIndexId, meta }),
  removeRef: (id: number, refId: number) => api.delete(`/api/posts/${id}/refs/${refId}`),
  reorderRefs: (id: number, refIds: number[]) => api.post(`/api/posts/${id}/refs/reorder`, { ref_ids: refIds }),
  getComments: (id: number, params?: Record<string, unknown>) =>
    api.get(`/api/posts/${id}/comments`, { params }),
  addComment: (id: number, content: string, parentId?: number) =>
    api.post(`/api/posts/${id}/comments`, { content, parent_id: parentId }),
  like: (id: number) => api.post(`/api/posts/${id}/like`),
  favorite: (id: number) => api.post(`/api/posts/${id}/favorite`)
}
