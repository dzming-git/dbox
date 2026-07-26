import api from '../api'

export type SettingScope = 'browser' | 'user' | 'global'

export interface SettingsData {
  autoplay: boolean
  defaultQuality: string
  subtitleLanguage: string
  theme: string
  language: string
  blockDisliked: boolean
  defaultSort: string
  defaultOrder: string
  enableNotifications: boolean
  notifyOnNewVideos: boolean
  [key: string]: unknown
}

// 与后端 SETTINGS_DEFAULTS 保持一致
export const DEFAULT_SETTINGS: SettingsData = {
  autoplay: false,
  defaultQuality: 'auto',
  subtitleLanguage: 'off',
  theme: 'dark',
  language: 'zh-CN',
  blockDisliked: false,
  defaultSort: 'recommended',
  defaultOrder: 'desc',
  enableNotifications: true,
  notifyOnNewVideos: true,
}

export const SETTING_KEYS = Object.keys(DEFAULT_SETTINGS) as (keyof SettingsData)[]

// 浏览器层（本机本浏览器）存储键
const BROWSER_SETTINGS_KEY = 'dplayer_browser_settings'

// 后端缓存：global 层（管理员全局默认）与 user 层（当前登录用户）
let serverGlobal: Partial<SettingsData> = {}
let serverUser: Partial<SettingsData> = {}
let serverIsAdmin = false

// 浏览器层：从 localStorage 读取
export function loadBrowserSettings(): Partial<SettingsData> {
  try {
    const raw = localStorage.getItem(BROWSER_SETTINGS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

// 浏览器层：合并保存（仅保留白名单键）
export function saveBrowserSettings(partial: Partial<SettingsData>): Partial<SettingsData> {
  const current = loadBrowserSettings()
  const merged = { ...current, ...partial }
  const cleaned: Partial<SettingsData> = {}
  for (const k of SETTING_KEYS) {
    if (k in merged) (cleaned as Record<string, unknown>)[k] = merged[k]
  }
  localStorage.setItem(BROWSER_SETTINGS_KEY, JSON.stringify(cleaned))
  return cleaned
}

// 浏览器层：删除指定键（回落到下一层）
export function resetBrowserSettings(keys?: string[]): Partial<SettingsData> {
  const current = loadBrowserSettings()
  const target = keys && keys.length ? keys : (SETTING_KEYS as string[])
  const cleaned: Partial<SettingsData> = {}
  for (const k of SETTING_KEYS) {
    if (!target.includes(k) && k in current) {
      (cleaned as Record<string, unknown>)[k] = (current as Record<string, unknown>)[k]
    }
  }
  localStorage.setItem(BROWSER_SETTINGS_KEY, JSON.stringify(cleaned))
  return cleaned
}

// 拉取后端分层设置（global + user），游客仅返回 global
export function fetchServerSettings(): Promise<void> {
  return api.get('/api/settings').then((res: any) => {
    if (res && res.success) {
      serverGlobal = res.global || {}
      serverUser = res.user || {}
      serverIsAdmin = !!res.is_admin
    }
  }).catch(() => {
    serverGlobal = {}
    serverUser = {}
    serverIsAdmin = false
  })
}

export function getIsAdmin(): boolean {
  return serverIsAdmin
}

// 登出或切换账号时清空后端缓存
export function clearServerSettings(): void {
  serverGlobal = {}
  serverUser = {}
}

export function getGlobalSettings(): Partial<SettingsData> {
  return serverGlobal
}
export function getUserSettings(): Partial<SettingsData> {
  return serverUser
}

// 合并优先级（高 -> 低）：browser > user > global > defaults
export function getEffectiveSettings(): SettingsData {
  const effective: Record<string, unknown> = { ...DEFAULT_SETTINGS }
  const browser = loadBrowserSettings()
  for (const k of SETTING_KEYS) {
    if (k in serverGlobal) effective[k] = (serverGlobal as Record<string, unknown>)[k]
    if (k in serverUser) effective[k] = (serverUser as Record<string, unknown>)[k]
    if (k in browser) effective[k] = (browser as Record<string, unknown>)[k]
  }
  return effective as SettingsData
}

// 追踪某键生效值来自哪一层（用于 UI 来源徽章）
export function getSettingSource(key: string): SettingScope | 'default' {
  const browser = loadBrowserSettings()
  if (key in browser) return 'browser'
  if (key in serverUser) return 'user'
  if (key in serverGlobal) return 'global'
  return 'default'
}

// 兼容 videoStore / galleryStore 调用
export function getDefaultSort(): { sort: string; order: string } {
  const s = getEffectiveSettings()
  return { sort: s.defaultSort, order: s.defaultOrder }
}

// 保存用户层（登录账号，跨设备）
export function saveUserSettings(partial: Partial<SettingsData>, resetKeys?: string[]): Promise<void> {
  return api.post('/api/settings', { scope: 'user', settings: partial, reset: resetKeys || [] }).then((res: any) => {
    if (res && res.success) serverUser = res.data || {}
  })
}

// 保存全局层（管理员，全站默认）
export function saveGlobalSettings(partial: Partial<SettingsData>, resetKeys?: string[]): Promise<void> {
  return api.post('/api/settings', { scope: 'global', settings: partial, reset: resetKeys || [] }).then((res: any) => {
    if (res && res.success) serverGlobal = res.data || {}
  })
}
