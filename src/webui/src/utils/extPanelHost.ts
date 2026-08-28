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
  return rootEl
}

function injectStylesOnce() {
  if (document.getElementById('dbox-ext-panel-style')) return
  const s = document.createElement('style')
  s.id = 'dbox-ext-panel-style'
  s.textContent = `
#${ROOT_ID} { position: fixed; inset: 0; pointer-events: none; z-index: 1200; }
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
#${ROOT_ID} .dbox-ext-panel[data-mode="hidden"] {
  display: none;
}
/* 小窗：右下角浮动面板 */
#${ROOT_ID} .dbox-ext-panel[data-mode="floating"] {
  right: 24px;
  bottom: 24px;
  width: 420px;
  height: 620px;
  max-width: calc(100vw - 32px);
  max-height: calc(100vh - 100px);
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
}
#${ROOT_ID} .dbox-ext-panel-btn:hover { color: #4f8cff; border-color: #4f8cff; }
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
  // 全屏态由 body class 表达，供全局导航隐藏等样式使用
  const anyFullscreen = Array.from(panels.values()).some(p => p.mode === 'fullscreen')
  document.body.classList.toggle(BODY_FULLSCREEN_CLASS, anyFullscreen)
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
  fsBtn.className = 'dbox-ext-panel-btn'
  fsBtn.textContent = '⛶ 全屏'
  fsBtn.title = '在独立页面全屏打开'
  fsBtn.style.display = opts.standaloneRoute ? '' : 'none'
  fsBtn.addEventListener('click', () => {
    if (opts.standaloneRoute) {
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
  minBtn.addEventListener('click', () => setPanelMode(extId, 'hidden'))

  head.appendChild(titleEl)
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
  root.appendChild(wrap)

  const entry: PanelEntry = {
    extId, wrap, iframe, titleEl, mode: 'hidden',
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
    const fsBtn = exist.wrap.querySelector('.dbox-ext-panel-btn') as HTMLButtonElement | null
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
  if (mode !== 'hidden') post(entry, { type: 'DBOX_MODE', fullscreen: mode === 'fullscreen' })
}

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

function startListening() {
  if (listening) return
  listening = true
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
