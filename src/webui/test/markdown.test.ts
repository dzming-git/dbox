import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '../src/utils/markdown'

describe('帖子正文的极简 Markdown 渲染', () => {
  it('渲染标题、粗体与列表', () => {
    const out = renderMarkdown('# 标题\n**粗** 和 `code`\n- 甲\n- 乙')
    expect(out).toContain('<h3>标题</h3>')
    expect(out).toContain('<strong>粗</strong>')
    expect(out).toContain('<code>code</code>')
    expect(out).toContain('<li>甲</li>')
  })

  it('转义 HTML：用户输入不会变成可执行标签', () => {
    const out = renderMarkdown('<img src=x onerror=alert(1)>')
    expect(out).not.toContain('<img')
    expect(out).toContain('&lt;img')
  })

  it('只放行 http(s) 链接，拒绝 javascript: 伪协议', () => {
    expect(renderMarkdown('[点我](https://a.com)')).toContain('href="https://a.com"')
    const bad = renderMarkdown('[点我](javascript:alert(1))')
    expect(bad).not.toContain('href="javascript')
  })

  it('不吞掉自研资源标记 [文字](res:ID:mode)', () => {
    // 该标记由 posts 的 renderSegments 处理，Markdown 渲染不得把它改成链接
    const out = renderMarkdown('看这个 [片子](res:12:embed)')
    expect(out).not.toContain('href="res:12')
    expect(out).toContain('[片子](res:12:embed)')
  })

  it('空内容返回空串', () => {
    expect(renderMarkdown('')).toBe('')
  })
})
