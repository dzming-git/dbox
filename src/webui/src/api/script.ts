import { api } from './index'

export interface ScriptParam {
  name: string
  label?: string
  type?: string
  required?: boolean
  default?: any
  enum?: string[]
  media_type?: string
  description?: string
  domain_filter?: string
  user_defaultable?: boolean
}

export interface ScriptUI {
  mount?: string
  title?: string
  icon?: string
  entry?: string
  needs_credential?: boolean
  sandbox?: string
  /** 独立全屏路由路径（如 "/ai-chat"），由框架动态注册；不声明则无独立页。 */
  standalone_route?: string
  /** 忙碌态/未读轮询接口（相对路径），声明后悬浮气泡入口会周期轮询该接口。 */
  busy_poll?: string
}

export interface ScriptInfo {
  id: string
  name: string
  description?: string
  runtime?: string
  interface?: string
  enabled: boolean
  params: ScriptParam[]
  required_cookies?: string[]
  error?: string
  ui?: ScriptUI
}

export interface CookieProfile {
  id: string
  kind?: string
  name: string
  domain: string
  format?: string
  note?: string
  created_at?: string
  updated_at?: string
}

export interface JobLog {
  level: string
  message: string
  ts: string
}

export interface PendingInput {
  prompt?: string
  options: { value: string; label: string }[]
  multi?: boolean
  min?: number
  max?: number
  allow_text?: boolean
  text_hint?: string
}

export interface ScriptJob {
  id: string
  script_id: string
  script_name: string
  status: string
  progress: number
  params: Record<string, any>
  result: any
  library_id: number | null
  notified: boolean
  error: string
  created_at: string
  updated_at: string
  awaiting: boolean
  pending_input: PendingInput | null
  logs: JobLog[]
}

export const scriptApi = {
  // 脚本管理（管理员）
  listScripts: (all = true) =>
    api.get('/api/admin/scripts', { params: all ? { all: 1 } : {} }),
  enable: (id: string) => api.post(`/api/admin/scripts/${id}/enable`),
  disable: (id: string) => api.post(`/api/admin/scripts/${id}/disable`),
  reload: () => api.post('/api/admin/scripts/reload'),

  // 运行 / 任务
  run: (id: string, params: Record<string, any>) =>
    api.post(`/api/scripts/${id}/run`, { params }),
  listJobs: () => api.get('/api/scripts/jobs'),
  getJob: (jobId: string) => api.get(`/api/scripts/jobs/${jobId}`),
  cancelJob: (jobId: string) => api.post(`/api/scripts/jobs/${jobId}/cancel`),
  respondJob: (jobId: string, value: any) =>
    api.post(`/api/scripts/jobs/${jobId}/respond`, { value }),

  // 凭证保险库（管理员）
  listCookies: () => api.get('/api/admin/cookies'),
  createCookie: (data: { kind?: string; name: string; domain: string; format?: string; value: string; note?: string }) =>
    api.post('/api/admin/cookies', data),
  updateCookie: (id: string, data: { kind?: string; name?: string; domain?: string; format?: string; value?: string; note?: string }) =>
    api.put(`/api/admin/cookies/${id}`, data),
  deleteCookie: (id: string) => api.delete(`/api/admin/cookies/${id}`),

  // 脚本参数用户默认值（管理员）
  getDefaults: (id: string) => api.get(`/api/admin/scripts/${id}/defaults`),
  saveDefaults: (id: string, defaults: Record<string, any>) =>
    api.put(`/api/admin/scripts/${id}/defaults`, { defaults }),

  // 扩展 UI 注入（仅管理员可见）：返回已启用且声明 ui 段的脚本
  listExtensions: () => api.get('/api/ui-extensions'),
  getPanel: (id: string) => api.get(`/api/ui-panel/${id}`),
}
