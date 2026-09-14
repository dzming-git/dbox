import { api } from './index'

/** 可导出的元数据类型 */
export type BackupKind =
  | 'videos'
  | 'tags'
  | 'collections'
  | 'watchlater'
  | 'history'
  | 'missing'
  | 'all'

export interface RemapReport {
  success: boolean
  dry_run: boolean
  matched: number
  updated: number
  would_update: number
  missing_target: number
  samples: { title: string; from: string; to: string; ok: boolean }[]
}

export const backupApi = {
  // 导出元数据为 JSON（返回 blob，由前端触发下载）
  exportJson: (what: BackupKind) =>
    api.get('/api/admin/backup/export', {
      params: { what },
      responseType: 'blob',
    }),
  // 合集导出为 M3U 播放列表
  exportCollectionM3u: (collectionId: number) =>
    api.get(`/api/admin/backup/collections/${collectionId}/m3u`, {
      responseType: 'blob',
    }),
  // 按前缀批量重映射（换机 / 目录搬家），默认试运行
  remapPrefix: (oldPrefix: string, newPrefix: string, dryRun = true) =>
    api.post('/api/admin/backup/remap-prefix', {
      old_prefix: oldPrefix,
      new_prefix: newPrefix,
      dry_run: dryRun,
    }) as Promise<RemapReport>,
}
