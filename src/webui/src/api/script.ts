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
  /** 独立全屏路由路径（如 "/codebuddy"），由框架动态注册；不声明则无独立页。 */
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
  has_value?: boolean
}

export interface VaultPayload {
  kind?: string
  name?: string
  domain: string
  format?: string
  note?: string
  value?: string
  cookies?: { name: string; value: string; domain?: string; path?: string }[]
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

/**
 * 插件独立全屏路由的命名空间（由后端框架强制）。
 *
 * 插件只在 manifest 的 ui.standalone_route 里声明自己的一段路径（如 "/codebuddy"），
 * 后端 list_extensions 统一加上 /ext 前缀后才是最终 URL（/ext/codebuddy）。
 * 这样插件无法直接占用根路径，也就不会与核心路由（/admin、/video 等）冲突。
 * 前端此处仅作幂等兜底，权威逻辑在后端。
 */
export const EXT_ROUTE_NS = '/ext'

/** 规范化独立路由：补前导斜杠并加上 /ext 命名空间（幂等，重复调用无副作用）。 */
export function normalizeStandaloneRoute(path?: string): string {
  let s = String(path || '').trim()
  if (!s) return ''
  if (!s.startsWith('/')) s = '/' + s
  if (s === EXT_ROUTE_NS || s.startsWith(EXT_ROUTE_NS + '/')) return s
  return EXT_ROUTE_NS + s
}

export const scriptApi = {
  // 脚本管理（管理员）
  listScripts: (all = true) =>
    api.get('/api/admin/scripts', { params: all ? { all: 1 } : {} }),
  enable: (id: string) => api.post(`/api/admin/scripts/${id}/enable`),
  disable: (id: string) => api.post(`/api/admin/scripts/${id}/disable`),
  reload: () => api.post('/api/admin/scripts/reload'),

  // 凭证保险库（管理员）
  listCookies: () => api.get('/api/admin/cookies'),
  getCookie: (id: string) => api.get(`/api/admin/cookies/${id}`),
  createCookie: (data: VaultPayload) => api.post('/api/admin/cookies', data),
  updateCookie: (id: string, data: VaultPayload) => api.put(`/api/admin/cookies/${id}`, data),
  deleteCookie: (id: string) => api.delete(`/api/admin/cookies/${id}`),

  // 脚本参数用户默认值（管理员）
  getDefaults: (id: string) => api.get(`/api/admin/scripts/${id}/defaults`),
  saveDefaults: (id: string, defaults: Record<string, any>) =>
    api.put(`/api/admin/scripts/${id}/defaults`, { defaults }),

  // 插件独立设置（由 manifest.settings schema 驱动）
  getSettings: (id: string) =>
    api.get(`/api/admin/scripts/${id}/settings`),
  saveSettings: (id: string, values: Record<string, any>) =>
    api.put(`/api/admin/scripts/${id}/settings`, { values }),

  // 扩展 UI 注入（仅管理员可见）：返回已启用且声明 ui 段的脚本。
  // standalone_route 的 /ext 命名空间由后端统一强制（extensions_host 的
  // list_extensions 负责规范化与默认推导），前端不做二次加工，避免两处逻辑漂移。
  listExtensions: () => api.get('/api/ui-extensions'),
  getPanel: (id: string) => api.get(`/api/ui-panel/${id}`),
}
