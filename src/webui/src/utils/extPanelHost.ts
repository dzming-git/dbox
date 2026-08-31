/**
 * 扩展面板实例管理器（框架层能力，对插件零侵入）
 *
 * ── 要解决的问题 ────────────────────────────────────────────────
 * 小窗（悬浮面板）与全屏（独立页）原本各自创建一个 srcdoc iframe：
 * 切换形态等于销毁旧文档、新建新文档，面板脚本从零启动，于是
 *   · 浏览位置、输入框内容、视频播放进度全部归零
 *   · 收起（最小化）后再打开，之前的现场也没了
 *
 * ── 为什么不是「移动 iframe 节点」────────────────────────────────
 * 浏览器规则：把 iframe 从 DOM 中移除再插入别处，会**重新加载**它的文档，
 * 状态一样丢失。因此唯一可靠的做法是让 iframe **永远待在同一个 DOM 位置**，
 * 形态差异只通过 CSS 表达。
 *
 * ── 本模块的方案：单实例常驻 + 纯 CSS 形态切换 ──────────────────
 * 每个扩展在 document.body 下有一个常驻容器（不随路由/组件销毁），
 * 形态由 data-mode 属性驱动，仅切换 CSS：
 *   hidden      最小化（display:none，DOM 仍在 → 再打开现场还在）
 *   floating    小窗（右下角浮动面板）
 *   fullscreen  全屏（铺满视口）
 * 由于 DOM 节点从不移动、文档从不重建，面板内的一切状态天然保留：
 * 滚动位置、正在输入的文字、未提交的表单、视频 currentTime 都原样不动。
 */

export type PanelMode = 'hidden' | 'floating' | 'fullscreen'

export interface PanelOptions {
  /** 面板 HTML（一般经 withExtRuntime 前置共享运行时） */
  html: string
  /** iframe sandbox 策略 */
  sandbox?: string
  /** 标题栏文字 */
  title?: string
  /** 该扩展的独立全屏路由（有则标题栏出现全屏入口） */
  standaloneRoute?: string
}

export interface PanelMessage {
  type: string
  extId?: string
  [k: string]: any
}

type MessageHandler = (msg: PanelMessage, extId: string) => void

const ROOT_ID = 'dbox-ext-panels'
/** 全屏时加在 body 上，用于隐藏全局导航，让面板独占视口 */
const BODY_FULLSCREEN_CLASS = 'ext-panel-fullscreen'

interface PanelEntry {
  extId: string
  wrap: HTMLDivElement
  mask: HTMLDivElement
  iframe: HTMLIFrameElement
  titleEl: HTMLSpanElement
  mode: PanelMode
  /** 面板文档是否已就绪（用于延迟推送） */
  ready: boolean
  /** 待推送消息队列（文档就绪前先缓存） */
  pending: any[]
  opts: PanelOptions
}

const panels = new Map<string, PanelEntry>()
const handlers = new Set<MessageHandler>()
let rootEl: HTMLDivElement | null = null
let listening = false

/**
 * 小窗（浮动面板）的「后退手势陷阱」。
 *
 * 打开小窗只是切 CSS 形态，dbox 自身的路由历史不变；于是用户做系统/浏览器
 * 的后退手势时，命中的是 dbox 应用的路由历史 —— 结果整页回退，而不是收起小窗。
 *
 * 解决：进入浮动形态时，在当前历史栈顶压入一条「哨兵」记录（复制当前路由的
 * history.state、URL 不变）。这样：
 *   · 后退手势优先弹出这条哨兵 → 我们拦截并收起小窗，dbox 仍停在原页面；
 *   · 由于 URL 未变、state 是 Vue Router 自己的形状，Vue Router 认为仍在当前
 *     路由、不会真正导航；
 *   · 面板内部若有可回退内容（灯箱/详情，由 iframe 自己的历史承载），会先被
 *     iframe 历史消费，等 iframe 历史耗尽、再后退才命中哨兵 → 收起小窗。
 * 离开浮动形态（收起/全屏）时撤掉哨兵，避免遗留陷阱误吞后续真正的页面后退。
 */
let sentinelExtId: string | null = null
/** 程序化收起时主动 pop 哨兵产生的 popstate 需被忽略，防止二次收起 */
let suppressPop = 0
/** 哨兵记录在 history.state 上的标记键，用于精确识别「弹出的是否正是我们的哨兵」 */
const SENTINEL_KEY = '__dboxPanelSentinel'

function ensureSentinel(extId: string) {
  if (sentinelExtId === extId) return
  // 理论上同一时刻只有一个浮动面板；若哨兵被别的扩展持有，先清掉它
  if (sentinelExtId) clearSentinel()
  // 复制当前路由 state（Vue Router 的形状），URL 不变，再加标记作为哨兵
  const base = (window.history.state && typeof window.history.state === 'object')
    ? (window.history.state as Record<string, unknown>)
    : null
  if (!base) return // 无路由 state 时不埋哨兵，退回原生后退，避免破坏路由
  try {
    const st = { ...base, [SENTINEL_KEY]: extId }
    window.history.pushState(st, '', window.location.href)
    sentinelExtId = extId
  } catch (e) { /* 极端环境不支持则放弃陷阱 */ }
}

/** 当前栈顶是否正是我们为 extId 压入的哨兵 */
function isSentinelTop(): boolean {
  const s = window.history.state as Record<string, unknown> | null
  return !!(s && typeof s === 'object' && s[SENTINEL_KEY] === sentinelExtId)
}

function clearSentinel() {
  if (sentinelExtId === null) return
  // 仅当哨兵确实位于栈顶时才 pop 并清空（如普通收起）；
  // 若被全屏路由 / keepPanel 跳转压在下面，保留 sentinelExtId 与记录，
  // 待其回到栈顶后由一次后退自然消费（陷阱随之重新生效）。
  if (isSentinelTop()) {
    sentinelExtId = null
    suppressPop++
    try { window.history.back() } catch (e) { /* ignore */ }
  }
}

function onPopState() {
  if (suppressPop > 0) { suppressPop--; return }
  if (!sentinelExtId) return
  const extId = sentinelExtId
  const entry = panels.get(extId)
  if (!entry) { sentinelExtId = null; return }
  // 仅拦截「浮动（小窗）」形态；全屏由路由自行处理
  if (entry.mode !== 'floating') return
  // 若哨兵此刻仍在栈顶，说明刚才弹出的是它「之上」的其它历史（如 keepPanel 路由跳转），
  // 并非哨兵本身 → 不应收起小窗，留给路由自己处理。
  if (isSentinelTop()) return
  // 否则弹出的正是哨兵 → 小窗内已无可回退内容，后退应「收起小窗」而非整页回退
  sentinelExtId = null
  setPanelMode(extId, 'hidden')
  window.dispatchEvent(new CustomEvent('dbox-ext-collapse', { detail: { extId } }))
}

/** 从全局同步导航栏高度到面板根元素（面板在 body 下，与 .app-container 同级，无法继承其 CSS 变量） */
function syncNavHeight() {
  const root = ensureRoot()
  const h = getComputedStyle(document.documentElement).getPropertyValue('--nav-height').trim()
  if (h) root.style.setProperty('--nav-height', h)
}

function ensureRoot(): HTMLDivElement {
  if (rootEl && document.body.contains(rootEl)) return rootEl
  const exist = document.getElementById(ROOT_ID) as HTMLDivElement | null
  if (exist) {
    rootEl = exist
    return rootEl
  }
  const el = document.createElement('div')
  el.id = ROOT_ID
  document.body.appendChild(el)
  rootEl = el
  // 首次创建时同步；后续窗口 resize 由外部按需调用
  syncNavHeight()
  return rootEl
}

function injectStylesOnce() {
  if (document.getElementById('dbox-ext-panel-style')) return
  const s = document.createElement('style')
  s.id = 'dbox-ext-panel-style'
  s.textContent = `
/* z-index 需同时高于：遮罩（.ext-mask = 8999）、面板打开时被抬起的导航栏
   （body.ext-panel-open .nav = 9003）与应用启动器（.ext-launcher = 9004）。
   低于遮罩会导致「点击面板内输入框即收起」；低于导航栏/启动器则面板标题栏
   （含全屏、收起按钮）被压在后面点不到。 */
#${ROOT_ID} { position: fixed; inset: 0; pointer-events: none; z-index: 9100; }
#${ROOT_ID} .dbox-ext-panel {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid #e3e6eb;
  border-radius: 12px;
  overflow: hidden;
  box-shadow: 0 12px 32px rgba(15,20,25,.18);
  pointer-events: auto;
}
/* 小窗外的透明遮罩：捕获窗外的点击并收起面板，避免穿透点到小窗背后的内容（误触）。
   仅在 floating 形态显示；全屏/隐藏时隐藏，且默认 display:none 不拦截任何事件。 */
#${ROOT_ID} .dbox-ext-panel-mask {
  position: absolute;
  inset: 0;
  background: transparent;
  pointer-events: auto;
  display: none;
  z-index: 0;
}
#${ROOT_ID} .dbox-ext-panel-mask[data-show="1"] { display: block; }
#${ROOT_ID} .dbox-ext-panel[data-mode="hidden"] {
  display: none;
}
/* 小窗：贴导航栏下方展开（与导航栏入口位置呼应），高度由 top/bottom 自适应。
   刻意不与导航栏区域重叠：既避免遮挡导航，也避免标题栏按钮被导航压住。 */
#${ROOT_ID} .dbox-ext-panel[data-mode="floating"] {
  right: 16px;
  top: calc(var(--nav-height, 60px) + 8px);
  bottom: 16px;
  width: 420px;
  height: auto;
  max-width: calc(100vw - 32px);
}
/* 窄屏：改为水平居中、左右等距的悬浮卡片（与桌面「小窗」语义一致，但更克制）。
   - 左右边距对称（不再贴右、也不再左空一大片），视觉比例规整；
   - 高度封顶，明显是「浮在页面上的小窗」而非贴边的细长条；
   - 窗外整片透明遮罩可点（含顶部导航区与底部留白），单手点窗外任意处即可收起，
     因此等距边距不会削弱单手可点性。 */
@media (max-width: 600px) {
  #${ROOT_ID} .dbox-ext-panel[data-mode="floating"] {
    left: 50%;
    right: auto;
    transform: translateX(-50%);
    top: calc(var(--nav-height, 60px) + 16px);
    bottom: auto;
    width: min(440px, calc(100vw - 36px));
    max-width: 100%;
    height: calc(100dvh - var(--nav-height, 60px) - 80px);
    max-height: calc(100dvh - var(--nav-height, 60px) - 80px);
  }
}
/* 全屏：铺满视口，层级高于导航与浮层 */
#${ROOT_ID} .dbox-ext-panel[data-mode="fullscreen"] {
  inset: 0;
  width: 100%;
  height: 100%;
  border: none;
  border-radius: 0;
  box-shadow: none;
  z-index: 3000;
}
#${ROOT_ID} .dbox-ext-panel-head {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 42px;
  padding: 0 10px 0 14px;
  background: #fff;
  border-bottom: 1px solid #eef0f4;
  flex-shrink: 0;
  pointer-events: auto;
}
#${ROOT_ID} .dbox-ext-panel-title {
  flex: 1;
  font-size: 14px;
  font-weight: 600;
  color: #1f2329;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
#${ROOT_ID} .dbox-ext-panel-btn {
  border: 1px solid #e3e6eb;
  background: #fff;
  color: #555;
  border-radius: 6px;
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
  white-space: nowrap;
  pointer-events: auto;
}
#${ROOT_ID} .dbox-ext-panel-btn:hover { color: #4f8cff; border-color: #4f8cff; }
/* 面板状态灯：通用原语，默认隐藏，由扩展 postMessage { type:'DBOX_LIGHT' } 驱动。
   框架只负责渲染与点击回传，灯的含义（主控中 / 已让出 / 同步中）完全由扩展决定。 */
#${ROOT_ID} .dbox-ext-panel-light {
  display: none;
  align-items: center;
  gap: 5px;
  border: 1px solid #e3e6eb;
  background: #fff;
  border-radius: 10px;
  font-size: 11px;
  line-height: 1;
  padding: 4px 8px;
  cursor: default;
  color: #555;
  white-space: nowrap;
  flex: none;
}
#${ROOT_ID} .dbox-ext-panel-light::before {
  content: '';
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c9ced6;
  flex: none;
}
#${ROOT_ID} .dbox-ext-panel-light[data-state="ok"]::before {
  background: #22c55e;
  box-shadow: 0 0 0 2px rgba(34, 197, 94, .18);
}
#${ROOT_ID} .dbox-ext-panel-light[data-state="warn"]::before {
  background: #f59e0b;
  box-shadow: 0 0 0 2px rgba(245, 158, 11, .18);
}
#${ROOT_ID} .dbox-ext-panel-light[data-state="idle"]::before { background: #c9ced6; }
#${ROOT_ID} .dbox-ext-panel-light[data-clickable="1"] { cursor: pointer; }
#${ROOT_ID} .dbox-ext-panel-light[data-clickable="1"]:hover { color: #4f8cff; border-color: #4f8cff; }
#${ROOT_ID} .dbox-ext-panel-frame {
  flex: 1;
  min-height: 0;
  width: 100%;
  border: none;
  background: #f7f8fa;
}
/* 全屏时隐藏全局导航/主内容，避免面板被压在下面或露出半截 */
body.${BODY_FULLSCREEN_CLASS} .nav,
body.${BODY_FULLSCREEN_CLASS} .main-content,
body.${BODY_FULLSCREEN_CLASS} .side-nav { display: none !important; }
`.trim()
  document.head.appendChild(s)
}

function applyMode(entry: PanelEntry, mode: PanelMode) {
  entry.mode = mode
  entry.wrap.dataset.mode = mode
  // 仅小窗形态显示遮罩（捕获窗外点击 → 收起）；全屏/隐藏时隐藏，避免拦截交互
  if (entry.mask) entry.mask.dataset.show = mode === 'floating' ? '1' : '0'
  // 全屏按钮文案随形态切换：全屏态显示「小窗」（点击切回），其余显示「全屏」
  const fsBtn = entry.wrap.querySelector('.dbox-ext-panel-fsbtn') as HTMLButtonElement | null
  if (fsBtn) {
    if (mode === 'fullscreen') {
      fsBtn.textContent = '▢ 小窗'
      fsBtn.title = '切换为小窗'
    } else {
      fsBtn.textContent = '⛶ 全屏'
      fsBtn.title = '在独立页面全屏打开'
    }
  }
  // 全屏态由 body class 表达，供全局导航隐藏等样式使用
  const anyFullscreen = Array.from(panels.values()).some(p => p.mode === 'fullscreen')
  document.body.classList.toggle(BODY_FULLSCREEN_CLASS, anyFullscreen)
  // 全屏时容器整体抬到导航（9003）/启动器（9004）之上，避免被压在下面。
  // 容器会创建层叠上下文，因此必须抬容器本身而非子元素。
  const root = ensureRoot()
  root.style.zIndex = anyFullscreen ? '9500' : '9100'
}

function post(entry: PanelEntry, msg: any) {
  const win = entry.iframe.contentWindow
  if (!win) return
  try {
    win.postMessage(msg, '*')
  } catch (e) { /* 忽略跨源/已销毁 */ }
}

function flushPending(entry: PanelEntry) {
  if (!entry.ready) return
  const q = entry.pending.splice(0, entry.pending.length)
  for (const m of q) post(entry, m)
}

function buildPanel(extId: string, opts: PanelOptions): PanelEntry {
  injectStylesOnce()
  const root = ensureRoot()

  const wrap = document.createElement('div')
  wrap.className = 'dbox-ext-panel'
  wrap.dataset.ext = extId
  wrap.dataset.mode = 'hidden'

  const head = document.createElement('div')
  head.className = 'dbox-ext-panel-head'

  const titleEl = document.createElement('span')
  titleEl.className = 'dbox-ext-panel-title'
  titleEl.textContent = opts.title || extId

  const fsBtn = document.createElement('button')
  fsBtn.className = 'dbox-ext-panel-btn dbox-ext-panel-fsbtn'
  fsBtn.textContent = '⛶ 全屏'
  fsBtn.title = '在独立页面全屏打开'
  fsBtn.style.display = opts.standaloneRoute ? '' : 'none'
  fsBtn.addEventListener('click', () => {
    if (!opts.standaloneRoute) return
    const cur = panels.get(extId)
    if (cur && cur.mode === 'fullscreen') {
      // 全屏态：按钮已变为「小窗」，点击切回小窗并离开全屏路由页
      window.dispatchEvent(new CustomEvent('dbox-ext-exit-fullscreen', {
        detail: { extId, mode: 'floating' },
      }))
      forceExitFullscreen(extId)
    } else {
      // 只切路由；iframe 不动，由全屏路由页把形态切成 fullscreen
      window.dispatchEvent(new CustomEvent('dbox-ext-request-fullscreen', {
        detail: { extId, route: opts.standaloneRoute },
      }))
    }
  })

  const minBtn = document.createElement('button')
  minBtn.className = 'dbox-ext-panel-btn'
  minBtn.textContent = '— 收起'
  minBtn.title = '收起面板（保留当前状态）'
  minBtn.addEventListener('click', () => {
    const cur = panels.get(extId)
    if (cur && cur.mode === 'fullscreen') {
      // 全屏态的「收起」需离开独立全屏路由页，回到进入前的页面；
      // 若只隐藏面板，全屏路由页（ExtensionStandalone）本身近乎空白，
      // 会留下「白屏」且无法返回上一页。由该路由页监听后执行 router.back。
      // 同时挂框架级兜底，防止路由异常时面板卡死（按钮点了无响应）。
      window.dispatchEvent(new CustomEvent('dbox-ext-exit-fullscreen', { detail: { extId } }))
      forceExitFullscreen(extId)
    } else {
      // 收起小窗：先立即隐藏（即时反馈），再通知宿主清理 openId，
      // 否则 body 的 ext-no-scroll（overflow:hidden）会残留，导致首页无法上下滑动。
      setPanelMode(extId, 'hidden')
      window.dispatchEvent(new CustomEvent('dbox-ext-collapse', { detail: { extId } }))
    }
  })

  // 面板状态灯（通用原语）：默认隐藏，由扩展 postMessage { type:'DBOX_LIGHT' } 驱动。
  // 框架只管渲染与点击回传，不掺任何插件语义。
  const lightBtn = document.createElement('button')
  lightBtn.className = 'dbox-ext-panel-light'
  lightBtn.type = 'button'
  lightBtn.dataset.state = 'idle'
  lightBtn.dataset.clickable = '0'
  lightBtn.addEventListener('click', () => {
    if (lightBtn.dataset.clickable !== '1') return
    post(entry, { type: 'DBOX_LIGHT_CLICK' })
  })

  head.appendChild(titleEl)
  head.appendChild(lightBtn)
  head.appendChild(fsBtn)
  head.appendChild(minBtn)

  const iframe = document.createElement('iframe')
  iframe.className = 'dbox-ext-panel-frame'
  iframe.setAttribute('sandbox', opts.sandbox || 'allow-scripts allow-same-origin allow-forms allow-popups')
  iframe.srcdoc = opts.html || ''
  iframe.addEventListener('load', () => {
    entry.ready = true
    flushPending(entry)
  })

  wrap.appendChild(head)
  wrap.appendChild(iframe)

  // 小窗遮罩：先于面板插入，使其绘制在面板之下；点击遮罩即收起面板
  const mask = document.createElement('div')
  mask.className = 'dbox-ext-panel-mask'
  mask.addEventListener('click', () => {
    const cur = panels.get(extId)
    if (cur && cur.mode === 'floating') {
      // 点遮罩收起：同上，必须通知宿主清理 openId 以解除背景滚动锁定
      setPanelMode(extId, 'hidden')
      window.dispatchEvent(new CustomEvent('dbox-ext-collapse', { detail: { extId } }))
    }
  })
  root.appendChild(mask)
  root.appendChild(wrap)

  const entry: PanelEntry = {
    extId, wrap, mask, iframe, titleEl, mode: 'hidden',
    ready: false, pending: [], opts,
  }
  panels.set(extId, entry)
  return entry
}

/** 创建（或复用）某扩展的面板实例。已存在则只更新标题/全屏路由，绝不重建 iframe。 */
export function ensurePanel(extId: string, opts: PanelOptions): void {
  const exist = panels.get(extId)
  if (exist) {
    exist.opts = { ...exist.opts, ...opts }
    if (opts.title) exist.titleEl.textContent = opts.title
    const fsBtn = exist.wrap.querySelector('.dbox-ext-panel-fsbtn') as HTMLButtonElement | null
    if (fsBtn) fsBtn.style.display = exist.opts.standaloneRoute ? '' : 'none'
    return
  }
  buildPanel(extId, opts)
}

/**
 * 切换形态（纯 CSS，DOM 与 iframe 文档均不动 → 面板内所有状态保留）。
 * 若面板尚未创建，先以 hidden 建好，等 ensurePanel 提供 HTML。
 */
export function setPanelMode(extId: string, mode: PanelMode): void {
  let entry = panels.get(extId)
  if (!entry) entry = buildPanel(extId, { html: '' })
  applyMode(entry, mode)
  // 小窗（浮动）回退陷阱：进入浮动时压哨兵、离开浮动（收起/全屏）时撤哨兵。
  // 保证「用户在小窗内无可回退内容时，系统/浏览器后退手势收起小窗而非整页回退」。
  if (mode === 'floating') ensureSentinel(extId)
  else clearSentinel()
  // 切到小窗时同步导航高度（窗口 resize 后 nav-height 可能已变）
  if (mode === 'floating') syncNavHeight()
  // 含 hidden：面板收起/最小化时也通知插件（如暂停内联视频，display:none 不会自动停媒体）
  post(entry, { type: 'DBOX_MODE', fullscreen: mode === 'fullscreen', hidden: mode === 'hidden' })
}

/**
 * 全屏态退出兜底：正常路径由 ExtensionStandalone 监听 dbox-ext-exit-fullscreen 后
 * router.back() 离开全屏路由页。但若因历史/哨兵状态错乱导致 router.back 没真正导航
 * （面板仍卡在全屏、按钮点了“无响应”），这里强制回退，保证面板一定能切出全屏。
 */
function forceExitFullscreen(extId: string) {
  setTimeout(() => {
    const e = panels.get(extId)
    if (!e || e.mode !== 'fullscreen') return
    try { window.history.back() } catch (_) { /* ignore */ }
    setTimeout(() => {
      const e2 = panels.get(extId)
      if (e2 && e2.mode === 'fullscreen') window.location.href = '/'
    }, 350)
  }, 600)
}

/** 外部可在 window resize 时调用，同步最新导航栏高度 */
export { syncNavHeight }

export function getPanelMode(extId: string): PanelMode | null {
  return panels.get(extId)?.mode ?? null
}

/** 有面板处于非隐藏态（用于判断「是否正在查看某扩展」） */
export function isPanelVisible(extId: string): boolean {
  const m = getPanelMode(extId)
  return m === 'floating' || m === 'fullscreen'
}

/** 更新面板 HTML（会重建文档，仅在需要主动刷新面板时使用；日常切换形态不要调用） */
export function setPanelHtml(extId: string, html: string, title?: string): void {
  const entry = panels.get(extId) ?? buildPanel(extId, { html: '' })
  entry.opts.html = html
  entry.ready = false
  entry.iframe.srcdoc = html
  if (title) setPanelTitle(extId, title)
}

export function setPanelTitle(extId: string, title: string): void {
  const entry = panels.get(extId)
  if (entry) entry.titleEl.textContent = title
}

/** 向面板推送消息；文档未就绪时排队，就绪后补发。 */
export function postToPanel(extId: string, msg: any): void {
  const entry = panels.get(extId)
  if (!entry) return
  if (entry.ready) post(entry, msg)
  else entry.pending.push(msg)
}

export function getPanelIframe(extId: string): HTMLIFrameElement | null {
  return panels.get(extId)?.iframe ?? null
}

/** 订阅面板发来的消息（统一入口，替代各组件各自监听 window message） */
export function onPanelMessage(handler: MessageHandler): () => void {
  handlers.add(handler)
  return () => handlers.delete(handler)
}

/** 面板状态灯：由扩展 postMessage { type:'DBOX_LIGHT', state, text?, title?, clickable? } 驱动。
 *  state: 'ok' 绿 / 'warn' 橙 / 'idle' 灰 / 'off' 隐藏。clickable 时点击向面板回传 DBOX_LIGHT_CLICK。
 *  语义完全归扩展（如「主控中 / 已让出」），框架只提供位置与交互外壳。 */
function applyPanelLight(extId: string, data: any): void {
  const entry = panels.get(extId)
  if (!entry) return
  const el = entry.wrap.querySelector('.dbox-ext-panel-light') as HTMLButtonElement | null
  if (!el) return
  const st = String(data.state || '')
  if (!st || st === 'off') { el.style.display = 'none'; return }
  el.style.display = 'flex'
  el.dataset.state = st
  el.textContent = data.text ? String(data.text) : ''
  el.title = data.title ? String(data.title) : ''
  el.dataset.clickable = data.clickable ? '1' : '0'
}

/** 供宿主侧直接设置状态灯；扩展一般用 postMessage DBOX_LIGHT 即可。 */
export function setPanelLight(
  extId: string,
  light: { state: string; text?: string; title?: string; clickable?: boolean },
): void {
  applyPanelLight(extId, light)
}

function startListening() {
  if (listening) return
  listening = true
  // 小窗后退陷阱：仅在我们压入哨兵期间生效，拦截「整页回退」改为收起小窗
  window.addEventListener('popstate', onPopState)
  window.addEventListener('message', (e: MessageEvent) => {
    const data = e.data
    if (!data || typeof data !== 'object') return
    // 定位来源：优先用面板自带的 extId，其次按 source 反查
    let extId: string = data.extId || ''
    if (!extId) {
      // 用 Array.from 而非直接迭代：项目 tsconfig target 较低，不开启 downlevelIteration
      const list = Array.from(panels.values())
      for (let i = 0; i < list.length; i++) {
        if (list[i].iframe.contentWindow === e.source) { extId = list[i].extId; break }
      }
    }
    if (!extId) return
    // 面板状态灯：框架只负责渲染与点击回传，语义由扩展决定
    if (data.type === 'DBOX_LIGHT') applyPanelLight(extId, data)
    const hs = Array.from(handlers)
    for (let i = 0; i < hs.length; i++) {
      try { hs[i](data as PanelMessage, extId) } catch (err) { /* 单个处理失败不影响其他 */ }
    }
  })
}
startListening()

/** 销毁某扩展面板（扩展被禁用/卸载时调用；日常切换形态请勿调用） */
export function destroyPanel(extId: string): void {
  const entry = panels.get(extId)
  if (!entry) return
  entry.wrap.remove()
  panels.delete(extId)
  const anyFullscreen = Array.from(panels.values()).some(p => p.mode === 'fullscreen')
  document.body.classList.toggle(BODY_FULLSCREEN_CLASS, anyFullscreen)
}

/** 关闭全部面板（登出等场景） */
export function destroyAllPanels(): void {
  for (const id of Array.from(panels.keys())) destroyPanel(id)
}
