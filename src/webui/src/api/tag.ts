// tag 相关 API（从原 index.ts 按业务域拆分，方法签名保持 1:1）
import api, { API_BASE, axios } from './client'

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

  // 批量删除标签
  batchDeleteTags: (ids: number[]) =>
    api.post('/api/tags/batch-delete', { ids }),

  // 批量移动标签到指定父级（parentId 为 null 表示顶级）
  batchMoveTags: (ids: number[], parentId: number | null) =>
    api.post('/api/tags/batch-move', { ids, parent_id: parentId }),

  // 合并标签：将 sourceIds 合并进 targetId
  mergeTags: (sourceIds: number[], targetId: number) =>
    api.post('/api/tags/merge', { source_ids: sourceIds, target_id: targetId }),

  // 搜索标签 - 用于智能提示
  searchTags: (keyword: string, libraryId?: number) =>
    api.get('/api/tags/search', { params: { q: keyword, library_id: libraryId } })
}
