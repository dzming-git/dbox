// 回收站（软删除）管理 API。
// 后端路由见 backend/api/library_api.py：
//   GET  /api/admin/trash          列出回收站资源
//   POST /api/admin/trash/restore  恢复（body: { type, hash }）
//   POST /api/admin/trash/purge    永久删除（body: { type, hash }）
//   POST /api/admin/trash/empty    清空回收站
import { api } from './client'

export const trashApi = {
  // 列出回收站中的所有资源（视频 + 图集）
  getTrash: () => api.get('/api/admin/trash'),
  // 恢复某项到原位置
  restoreTrash: (type: string, hash: string) =>
    api.post('/api/admin/trash/restore', { type, hash }),
  // 永久删除某项
  purgeTrash: (type: string, hash: string) =>
    api.post('/api/admin/trash/purge', { type, hash }),
  // 清空整个回收站
  emptyTrash: () => api.post('/api/admin/trash/empty'),
}
