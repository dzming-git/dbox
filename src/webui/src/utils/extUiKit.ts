/**
 * 插件 UI Kit（框架层能力，对插件零侵入）
 *
 * 问题：插件面板是 srcdoc iframe + 自带 CSS，宿主的主题、圆角、字号传不进去，
 * 用户在插件与主站之间切换会感觉像两个产品。
 *
 * 做法：在把 panel.html 交给 iframe 之前，往 <head> 开头注入两段——
 *  1. 一段 <style>：把宿主当前的主题变量原样声明到面板的 :root 上，
 *     并提供一组 `.dbox-ui-*` 组件类（按钮 / 卡片 / 输入框 …）；
 *  2. 一小段脚本：监听宿主推来的 `DBOX_THEME` 消息，实时更新变量，
 *     这样用户换主题时面板会跟着变，而不必重建文档。
 *
 * 约束（很重要）：
 *  - **不设置任何元素级全局样式**（不碰 body/button 裸标签），只给变量与
 *    `.dbox-ui-*` 类。插件已有样式不会被改变，新插件则可直接复用 UI Kit；
 *  - 注入插在 <head> 最前面，因此插件自己的 CSS 天然可以覆盖它。
 */

import { broadcastToPanels } from './extPanelHost'

/** 需要从宿主透传给面板的变量（与 theme.css 保持一致） */
const THEME_VARS = [
  '--bg-base', '--bg-elevated', '--bg-surface', '--bg-surface-hover',
  '--bg-surface-2', '--bg-input', '--card-bg',
  '--border-subtle', '--border-default', '--border-strong',
  '--text-primary', '--text-secondary', '--text-tertiary', '--text-on-accent',
  '--accent', '--accent-hover', '--accent-active', '--accent-soft',
  '--accent-border',
  '--danger', '--danger-soft', '--warning', '--warning-soft',
  '--success', '--success-soft', '--info', '--info-soft',
  '--radius-sm', '--radius-md', '--radius-lg', '--radius-pill',
  '--shadow-sm', '--shadow-md',
  '--font-sans',
]

/** UI Kit 组件类：只用上面这些变量，因此在任何主题下都成立 */
const KIT_CSS = `
.dbox-ui-btn{display:inline-flex;align-items:center;gap:6px;background:var(--bg-surface-hover);color:var(--text-primary);border:1px solid var(--border-default);border-radius:var(--radius-sm);padding:6px 12px;font-size:13px;font-family:var(--font-sans);cursor:pointer;transition:border-color .15s ease,background .15s ease}
.dbox-ui-btn:hover{border-color:var(--accent-border)}
.dbox-ui-btn:disabled{opacity:.5;cursor:not-allowed}
.dbox-ui-btn.primary{background:var(--accent);color:var(--text-on-accent);border-color:transparent}
.dbox-ui-btn.primary:hover{background:var(--accent-hover)}
.dbox-ui-btn.danger{color:var(--danger);border-color:var(--danger-soft)}
.dbox-ui-btn.ghost{background:transparent}
.dbox-ui-card{background:var(--bg-surface);border:1px solid var(--border-default);border-radius:var(--radius-md);padding:12px 14px}
.dbox-ui-card + .dbox-ui-card{margin-top:10px}
.dbox-ui-input{background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border-default);border-radius:var(--radius-sm);padding:6px 10px;font-size:13px;font-family:var(--font-sans);width:100%;box-sizing:border-box}
.dbox-ui-input:focus{outline:none;border-color:var(--accent-border)}
.dbox-ui-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dbox-ui-col{display:flex;flex-direction:column;gap:8px}
.dbox-ui-title{margin:0 0 4px;font-size:14px;font-weight:600;color:var(--text-primary);font-family:var(--font-sans)}
.dbox-ui-text{font-size:13px;color:var(--text-secondary);line-height:1.6;font-family:var(--font-sans)}
.dbox-ui-muted{font-size:12px;color:var(--text-tertiary);font-family:var(--font-sans)}
.dbox-ui-badge{display:inline-block;font-size:11px;padding:2px 8px;border-radius:var(--radius-pill);background:var(--accent-soft);color:var(--accent);font-family:var(--font-sans)}
.dbox-ui-badge.ok{background:var(--success-soft);color:var(--success)}
.dbox-ui-badge.warn{background:var(--warning-soft);color:var(--warning)}
.dbox-ui-badge.bad{background:var(--danger-soft);color:var(--danger)}
.dbox-ui-empty{text-align:center;color:var(--text-secondary);padding:28px 0;font-size:13px;font-family:var(--font-sans)}
.dbox-ui-sep{height:1px;background:var(--border-subtle);margin:10px 0}
`

/** 读取宿主当前的主题变量值（空的跳过，避免写入空变量覆盖插件自带值） */
export function collectThemeVars(): Record<string, string> {
  const out: Record<string, string> = {}
  try {
    const cs = getComputedStyle(document.documentElement)
    for (const name of THEME_VARS) {
      const v = (cs.getPropertyValue(name) || '').trim()
      if (v) out[name] = v
    }
  } catch (e) {
    /* 取不到就交给插件自带样式 */
  }
  return out
}

function buildStyle(vars: Record<string, string>): string {
  const decl = Object.keys(vars)
    .map((k) => `${k}:${vars[k]}`)
    .join(';')
  return `<style id="dbox-ui-kit">:root{${decl}}
html{color-scheme:normal;font-family:var(--font-sans)}
${KIT_CSS}</style>`
}

function buildBridge(): string {
  // 换主题时由宿主 postMessage 推新值：直接改 :root 变量，不重建文档，
  // 面板里正在输入的内容、滚动位置全都保留。
  return `<script>
(function(){
  function apply(vars){
    var r = document.documentElement;
    for (var k in vars){ if (Object.prototype.hasOwnProperty.call(vars,k)) r.style.setProperty(k, vars[k]); }
  }
  window.addEventListener('message', function(e){
    var d = e.data;
    if (d && d.type === 'DBOX_THEME' && d.vars) apply(d.vars);
  });
})();
<\/script>`
}

/** 主题变化后推给所有面板（面板内即时换肤，不重建文档、不丢现场）。 */
export function pushThemeToPanels(): void {
  try {
    broadcastToPanels({ type: 'DBOX_THEME', vars: collectThemeVars() })
  } catch (e) {
    /* 面板未创建或广播失败都不影响主站 */
  }
}

/**
 * 给面板 HTML 注入主题变量 + UI Kit。
 * 注入失败时原样返回，绝不影响面板本体加载。
 */
export function withExtUiKit(html: string, extId: string): string {
  if (!html || typeof html !== 'string' || !extId) return html
  const inject = buildStyle(collectThemeVars()) + buildBridge()
  const headIdx = html.search(/<head[^>]*>/i)
  if (headIdx >= 0) {
    const insertAt = html.indexOf('>', headIdx) + 1
    return html.slice(0, insertAt) + inject + html.slice(insertAt)
  }
  return inject + html
}
