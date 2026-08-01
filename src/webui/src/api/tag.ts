// 标签相关 API
import api from './client'

export const tagApi = {
  getTags: () => api.get('/api/tags'),
  createTag: (name: string, parentId?: number | null) =>
    api.post('/api/tags', { name, parent_id: parentId }),
  // 全量标签树（含 path、qualifiers 等）
  getTagTree: () => api.get('/api/tags/tree'),
  deleteTag: (id: number) => api.delete(`/api/tags/${id}`),
  renameTag: (id: number, name: string) => api.put(`/api/tags/${id}`, { name }),
  getTagVideos: (id: number, params?: Record<string, unknown>) =>
    api.get(`/api/tags/${id}/videos`, { params }),
  // 标签建议（按前缀/关键字）
  suggest: (keyword: string, parentId?: number) =>
    api.get('/api/tags/suggest', { params: { keyword, parent_id: parentId } }),
  // 仅创建标签路径（不关联视频），返回末端 Tag
  createPath: (path: string, libraryId?: number) =>
    api.post('/api/tags/path', { path, library_id: libraryId })
}
