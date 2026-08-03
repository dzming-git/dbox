import { api } from './index'

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'awaiting_input'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type TaskKind = 'script' | 'upload' | 'thumbnail'

export interface Task {
  task_id: string
  kind: TaskKind
  title: string
  status: TaskStatus
  progress: number
  stage?: string | null
  detail?: string | null
  owner_id?: number | null
  library_id?: number | null
  action_required: boolean
  action_role?: 'user' | 'admin' | null
  action_kind?: 'script_interactive' | 'navigate' | null
  action_hint?: string | null
  action_data?: any
  created_at: number
  updated_at: number
}

export const taskApi = {
  // 当前用户可见的任务列表 + 红点计数
  list: () => api.get('/api/tasks'),
  // 轻量红点计数（导航栏轮询）
  actionCount: () => api.get('/api/tasks/action-count'),
  // 任务详情
  detail: (taskId: string) => api.get(`/api/tasks/${taskId}`),
  // 删除一条已结束的任务（进行中不允许）
  delete: (taskId: string) => api.delete(`/api/tasks/${taskId}`),
}
