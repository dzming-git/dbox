import { api } from './index'

export type TaskStatus =
  | 'pending'
  | 'running'
  | 'awaiting_input'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type TaskKind = 'scan' | 'script' | 'upload' | 'thumbnail' | (string & {})

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
  params?: any
  /** 已收到取消请求：任务会在下一个检查点自行停止，此时状态仍可能是 running */
  cancel_requested?: boolean
  /** 已重试次数 */
  attempts?: number
  started_at?: number | null
  finished_at?: number | null
  error_code?: string | null
  created_at: number
  updated_at: number
  /**
   * 是否支持「从中断处继续」。由**框架按能力注册表**判定后下发：
   * 任务类型注册了继续实现才为 true。界面不应自己列举哪些 kind 可继续。
   */
  can_resume?: boolean
}

/** 进行中（可请求取消） */
export const ACTIVE_STATUSES: TaskStatus[] = ['pending', 'running', 'awaiting_input']

/** 任务列表查询条件：状态/类型支持逗号分隔多选，active 表示进行中 */
export interface TaskQuery {
  status?: string
  kind?: string
  limit?: number
  offset?: number
}

export const taskApi = {
  // 当前用户可见的任务列表（可筛选分页）+ 红点计数
  list: (params?: TaskQuery) => api.get('/api/tasks', { params }),
  // 轻量红点计数（导航栏轮询）
  actionCount: () => api.get('/api/tasks/action-count'),
  // 任务详情
  detail: (taskId: string) => api.get(`/api/tasks/${taskId}`),
  // 删除一条已结束的任务（进行中不允许）
  delete: (taskId: string) => api.delete(`/api/tasks/${taskId}`),
  // 重试一个失败/已取消的任务
  retry: (taskId: string) => api.post(`/api/tasks/${encodeURIComponent(taskId)}/retry`),
  // 从中断处继续：统一入口，由框架查能力注册表后转交实现方
  resume: (taskId: string) => api.post(`/api/tasks/${encodeURIComponent(taskId)}/resume`),
  // 请求取消一个进行中的任务（协作式：任务会在下一个检查点停止）
  cancel: (taskId: string) => api.post(`/api/tasks/${encodeURIComponent(taskId)}/cancel`),
}
