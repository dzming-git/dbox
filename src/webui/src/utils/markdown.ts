/**
 * 极简 Markdown 渲染（帖子正文用）
 *
 * 为什么不用 marked / markdown-it：
 *  - 正文里混着自研的内联资源标记 `[文字](res:ID:mode)`，通用解析器会把它当普通链接，
 *    与现有「插入资源」能力冲突；
 *  - 引入通用库意味着要处理 raw HTML 带来的注入面，而本地应用不该为此付出代价。
 *
 * 因此这里只支持策展真正需要的几种写法，并且**先做 HTML 转义再生成标签**——
 * 用户输入永远不会变成可执行标签。
 *
 * 支持：# 标题、*斜体*、**粗体**、`代码`、- 列表、[文字](网址) 链接、段落与换行。
 */

/** 转义：所有用户输入进入 HTML 前必须先过这一层 */
function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

/** 行内渲染（输入已转义） */
function inline(s: string): string {
  let out = s
  // 行内代码优先，避免其中的 * _ 被当成强调
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>')
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
  // 只认 http(s) 开头的链接，杜绝 javascript: 之类的伪协议
  out = out.replace(
    /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener">$1</a>'
  )
  return out
}

/**
 * 把 Markdown 文本渲染成 HTML。
 * 返回的 HTML 可直接交给 v-html（内容已转义，且不含用户可控的标签属性）。
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  const lines = String(text).split(/\r?\n/)
  const html: string[] = []
  let listOpen = false

  const closeList = () => {
    if (listOpen) {
      html.push('</ul>')
      listOpen = false
    }
  }

  for (const raw of lines) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      closeList()
      continue
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/)
    if (h) {
      closeList()
      const lv = Math.min(h[1].length + 2, 6) // h1->h3：页面标题留给帖子自身
      html.push(`<h${lv}>${inline(esc(h[2]))}</h${lv}>`)
      continue
    }
    const li = line.match(/^\s*[-*]\s+(.*)$/)
    if (li) {
      if (!listOpen) {
        html.push('<ul>')
        listOpen = true
      }
      html.push(`<li>${inline(esc(li[1]))}</li>`)
      continue
    }
    closeList()
    html.push(`<p>${inline(esc(line))}</p>`)
  }
  closeList()
  return html.join('')
}
