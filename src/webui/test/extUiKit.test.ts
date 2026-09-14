// @vitest-environment jsdom
import { describe, it, expect, beforeEach } from 'vitest'
import { withExtUiKit, collectThemeVars } from '../src/utils/extUiKit'

const PANEL = `<!doctype html><html><head>
<style>.mine{color:red}</style>
</head><body><div id="app">hi</div></body></html>`

describe('插件 UI Kit 注入', () => {
  beforeEach(() => {
    document.documentElement.style.setProperty('--accent', '#ff0000')
    document.documentElement.style.setProperty('--bg-surface', '#101010')
    document.documentElement.style.setProperty('--text-primary', '#ffffff')
  })

  it('透传宿主主题变量', () => {
    expect(collectThemeVars()['--accent']).toBe('#ff0000')
  })

  it('把变量与组件类注入到 <head> 最前面（插件自己的样式可覆盖它）', () => {
    const out = withExtUiKit(PANEL, 'demo')
    expect(out).toContain('<style id="dbox-ui-kit">')
    expect(out).toContain('--accent:#ff0000')
    expect(out).toContain('.dbox-ui-btn')
    // 注入点必须早于插件自带样式，否则插件无法覆盖默认
    expect(out.indexOf('dbox-ui-kit')).toBeLessThan(out.indexOf('.mine'))
  })

  it('带上主题桥接脚本，支持运行时换肤', () => {
    const out = withExtUiKit(PANEL, 'demo')
    expect(out).toContain('DBOX_THEME')
  })

  it('不注入任何元素级全局样式（避免破坏既有插件）', () => {
    const out = withExtUiKit(PANEL, 'demo')
    // 只允许 :root 变量声明与 html{font-family}，不应出现裸标签配色
    expect(out).not.toMatch(/body\s*\{/)
    expect(out).not.toMatch(/button\s*\{/)
  })

  it('输入非法时原样返回，不影响面板加载', () => {
    expect(withExtUiKit('', 'demo')).toBe('')
    expect(withExtUiKit(PANEL, '')).toBe(PANEL)
  })
})
