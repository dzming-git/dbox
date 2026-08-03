/**
 * 主题注册表（Theme Registry）
 *
 * 设计目标：所有颜色都收敛到「几组核心色号 + 计算函数」，业务组件只引用 var(--xxx)。
 * 不再允许散落的硬编码色值 / 重复的 CSS 变量块。
 *
 * 每个主题 ThemeDef 提供：
 *  - id        唯一标识，设置项存储的就是这个 id
 *  - label     界面展示名
 *  - mode      'dark' | 'light'，用于区分明暗（影响阴影强度、边框透明度等）
 *  - base      核心色号（仅少量几个，作为计算输入）
 *  - build()   基于 base 推导出完整 CSS 变量 token 集（含 accent 的 hover/active/soft/border 派生）
 *
 * 渲染时通过 getTheme(id) 查到定义并 applyThemeById(id) 注入 :root 变量即可。
 */

export type ThemeMode = 'dark' | 'light'

/** 主题计算输出的完整 token（key 必须是 CSS 变量名，不带 -- 前缀） */
export type ThemeTokens = Record<string, string>

/** 核心色号（作为所有派生色的输入，数量保持最小集） */
export interface ThemeBase {
  bgBase: string
  bgElevated: string
  bgSurface: string
  bgSurfaceHover: string
  bgSurface2: string
  bgInput: string
  textPrimary: string
  textSecondary: string
  textTertiary: string
  accent: string
  danger: string
  warning: string
  success: string
  info: string
}

export interface ThemeDef {
  id: string
  label: string
  mode: ThemeMode
  base: ThemeBase
  /** 可选：在核心 token 之外补充自定义变量（如 nav 半透明背景） */
  extra?: ThemeTokens
}

/* ============================================================
   颜色计算工具
   基于核心色号推导出 hover / active / soft / border / 阴影等
   ============================================================ */

function clamp(n: number): number {
  return Math.max(0, Math.min(255, n))
}

function hexToRgb(hex: string): [number, number, number] {
  let h = hex.replace('#', '').trim()
  if (h.length === 3) h = h.split('').map((c) => c + c).join('')
  const num = parseInt(h, 16)
  return [(num >> 16) & 255, (num >> 8) & 255, num & 255]
}

function rgbToHex(r: number, g: number, b: number): string {
  return '#' + [r, g, b].map((v) => clamp(Math.round(v)).toString(16).padStart(2, '0')).join('')
}

function mix(a: string, b: string, weight: number): string {
  const [ar, ag, ab] = hexToRgb(a)
  const [br, bg, bb] = hexToRgb(b)
  return rgbToHex(ar + (br - ar) * weight, ag + (bg - ag) * weight, ab + (bb - ab) * weight)
}

/** 调亮/调暗：amount>0 变亮，<0 变暗 */
function shade(hex: string, amount: number): string {
  const [r, g, b] = hexToRgb(hex)
  if (amount >= 0) return rgbToHex(r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount)
  return rgbToHex(r * (1 + amount), g * (1 + amount), b * (1 + amount))
}

/** rgba 字符串（用于 soft 背景 / 边框 / 阴影） */
function withAlpha(hex: string, alpha: number): string {
  const [r, g, b] = hexToRgb(hex)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function isDark(mode: ThemeMode): boolean {
  return mode === 'dark'
}

/**
 * 根据 mode 与核心色号推导出完整 token 集。
 * 深色模式阴影更重、边框用白色低透明度；浅色反之。
 */
function buildTokens(mode: ThemeMode, base: ThemeBase, extra?: ThemeTokens): ThemeTokens {
  const dark = isDark(mode)
  const borderAlpha = dark ? 0.1 : 0.1
  const borderStrongAlpha = dark ? 0.18 : 0.16
  const shadowAlpha = dark ? (0.5 as number) : (0.08 as number)

  const tokens: ThemeTokens = {
    /* —— 中性背景 / 表面 —— */
    'bg-base': base.bgBase,
    'bg-elevated': base.bgElevated,
    'bg-surface': base.bgSurface,
    'card-bg': base.bgSurface,
    'bg-surface-hover': base.bgSurfaceHover,
    'bg-surface-2': base.bgSurface2,
    'bg-input': base.bgInput,

    /* —— 边框 —— */
    'border-subtle': dark ? 'rgba(255,255,255,0.06)' : 'rgba(20,20,30,0.06)',
    'border-default': withAlpha(dark ? '#ffffff' : '#14141e', borderAlpha),
    'border-color': withAlpha(dark ? '#ffffff' : '#14141e', borderAlpha),
    'border-strong': withAlpha(dark ? '#ffffff' : '#14141e', borderStrongAlpha),

    /* —— 文本 —— */
    'text-primary': base.textPrimary,
    'text-secondary': base.textSecondary,
    'text-tertiary': base.textTertiary,
    'text-on-accent': '#ffffff',

    /* —— 品牌强调色（由核心 accent 派生出一族）—— */
    'accent': base.accent,
    'accent-hover': shade(base.accent, dark ? 0.12 : 0.12),
    'accent-active': shade(base.accent, dark ? -0.08 : -0.12),
    'accent-soft': withAlpha(base.accent, dark ? 0.16 : 0.1),
    'accent-soft-hover': withAlpha(base.accent, dark ? 0.24 : 0.16),
    'accent-border': withAlpha(base.accent, dark ? 0.55 : 0.42),
    'primary': base.accent,

    /* —— 语义色（由核心色派生 soft）—— */
    'danger': base.danger,
    'danger-soft': withAlpha(base.danger, dark ? 0.16 : 0.12),
    'warning': base.warning,
    'warning-soft': withAlpha(base.warning, dark ? 0.16 : 0.14),
    'success': base.success,
    'success-soft': withAlpha(base.success, dark ? 0.16 : 0.12),
    'info': base.info,
    'info-soft': withAlpha(base.info, dark ? 0.16 : 0.12),

    /* —— 阴影 —— */
    'shadow-sm': `0 1px 2px rgba(0,0,0,${dark ? 0.4 : 0.06})`,
    'shadow-md': `0 4px 16px rgba(0,0,0,${dark ? 0.5 : shadowAlpha})`,
    'shadow-lg': `0 12px 32px rgba(0,0,0,${dark ? 0.6 : shadowAlpha + 0.04})`,

    /* —— 圆角 / 间距 / 过渡 / 字体（与主题色无关，保持统一）—— */
    'radius-sm': '6px',
    'radius-md': '10px',
    'radius-lg': '16px',
    'radius-xl': '22px',
    'radius-pill': '999px',
    'space-1': '4px',
    'space-2': '8px',
    'space-3': '12px',
    'space-4': '16px',
    'space-5': '24px',
    'space-6': '32px',
    'transition-fast': '0.15s ease',
    'transition': '0.22s cubic-bezier(0.4, 0, 0.2, 1)',
    'font-sans':
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif",

    /* 导航栏半透明背景 */
    'nav-bg': withAlpha(base.bgElevated, 0.82),
  }

  if (extra) Object.assign(tokens, extra)
  return tokens
}

/* ============================================================
   主题注册表：新增皮肤只需在此追加一条 ThemeDef
   ============================================================ */

export const THEMES: ThemeDef[] = [
  {
    id: 'sunset-dark',
    label: '落日橙 · 深色',
    mode: 'dark',
    base: {
      bgBase: '#0f1115',
      bgElevated: '#1c1f26',
      bgSurface: '#1a1d24',
      bgSurfaceHover: '#242832',
      bgSurface2: '#2a2f3a',
      bgInput: '#242832',
      textPrimary: '#f2f4f8',
      textSecondary: '#b3b8c4',
      textTertiary: '#7c828f',
      accent: '#f97316',
      danger: '#ff6b70',
      warning: '#fbbf24',
      success: '#4ade80',
      info: '#60a5fa',
    },
  },
  {
    id: 'sunset-light',
    label: '落日橙 · 浅色',
    mode: 'light',
    base: {
      bgBase: '#f5f6f8',
      bgElevated: '#ffffff',
      bgSurface: '#ffffff',
      bgSurfaceHover: '#f0f1f4',
      bgSurface2: '#e9eaf0',
      bgInput: '#f1f2f5',
      textPrimary: '#1c1e26',
      textSecondary: '#5a5e6b',
      textTertiary: '#9398a5',
      accent: '#ea580c',
      danger: '#e5484d',
      warning: '#f59e0b',
      success: '#16a34a',
      info: '#2563eb',
    },
  },
  {
    id: 'midnight',
    label: '午夜蓝 · 深色',
    mode: 'dark',
    base: {
      bgBase: '#0b1020',
      bgElevated: '#131a2e',
      bgSurface: '#101729',
      bgSurfaceHover: '#1b2238',
      bgSurface2: '#222b45',
      bgInput: '#1b2238',
      textPrimary: '#eaf0ff',
      textSecondary: '#9fb0d0',
      textTertiary: '#6b7ba0',
      accent: '#3b82f6',
      danger: '#ff6b70',
      warning: '#fbbf24',
      success: '#4ade80',
      info: '#60a5fa',
    },
  },
  {
    id: 'forest',
    label: '森野绿 · 深色',
    mode: 'dark',
    base: {
      bgBase: '#0e1512',
      bgElevated: '#16201b',
      bgSurface: '#131c18',
      bgSurfaceHover: '#1e2a24',
      bgSurface2: '#27352d',
      bgInput: '#1e2a24',
      textPrimary: '#e8f3ec',
      textSecondary: '#a4bcae',
      textTertiary: '#70897b',
      accent: '#22c55e',
      danger: '#ff6b70',
      warning: '#fbbf24',
      success: '#4ade80',
      info: '#60a5fa',
    },
  },
  {
    id: 'rose',
    label: '蔷薇粉 · 浅色',
    mode: 'light',
    base: {
      bgBase: '#fbf3f5',
      bgElevated: '#ffffff',
      bgSurface: '#ffffff',
      bgSurfaceHover: '#fbe9ee',
      bgSurface2: '#f6dde4',
      bgInput: '#fbe9ee',
      textPrimary: '#2a1f24',
      textSecondary: '#7a646d',
      textTertiary: '#b09aa3',
      accent: '#e11d8f',
      danger: '#e5484d',
      warning: '#f59e0b',
      success: '#16a34a',
      info: '#2563eb',
    },
  },
]

const THEME_MAP = new Map(THEMES.map((t) => [t.id, t]))

export function getTheme(id: string): ThemeDef | undefined {
  return THEME_MAP.get(id)
}

export const DEFAULT_THEME_ID = 'sunset-dark'

export function getThemeOptions(): { v: string; t: string }[] {
  return THEMES.map((t) => ({ v: t.id, t: t.label }))
}

/** 计算主题 token，供调试/预览使用 */
export function computeThemeTokens(id: string): ThemeTokens {
  const def = getTheme(id) || getTheme(DEFAULT_THEME_ID)!
  return buildTokens(def.mode, def.base, def.extra)
}

/**
 * 通过主题 id 应用主题：查注册表 -> 计算 token -> 注入 :root CSS 变量。
 * 同时设置 data-mode 标记，供组件按明暗微调（极少数场景）。
 */
export function applyThemeById(id: string): void {
  const def = getTheme(id) || getTheme(DEFAULT_THEME_ID)!
  const tokens = buildTokens(def.mode, def.base, def.extra)
  const root = document.documentElement
  for (const [k, v] of Object.entries(tokens)) {
    root.style.setProperty(`--${k}`, v)
  }
  root.setAttribute('data-theme', def.id)
  root.setAttribute('data-mode', def.mode)
  // 兼容旧逻辑：body class 仍保留 light/dark，避免遗漏依赖它的样式
  document.body.classList.remove('light-theme', 'dark-theme')
  document.body.classList.add(def.mode === 'dark' ? 'dark-theme' : 'light-theme')
}
