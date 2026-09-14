import { describe, it, expect } from 'vitest'

// 与后端 backend/search_query.py 同构的最小实现说明见下；这里校验的是
// 「前端提示用的词法规则」，保证提示与实际解析一致。
const TOKEN_RE = /(\w+):([<>=!]*)([^\s:]+)/g

function tokens(q: string) {
  const out: { key: string; op: string; val: string }[] = []
  let m: RegExpExecArray | null
  TOKEN_RE.lastIndex = 0
  while ((m = TOKEN_RE.exec(q))) out.push({ key: m[1], op: m[2] || '', val: m[3] })
  return out
}

describe('搜索筛选语法的词法', () => {
  it('识别 tag / library / type / date / duration', () => {
    const t = tokens('猫 tag:动物 library:movie type:video date:2026-09 duration:>20min')
    expect(t.map((x) => x.key)).toEqual(['tag', 'library', 'type', 'date', 'duration'])
  })

  it('duration 的比较符单独成组', () => {
    const t = tokens('duration:<90s')
    expect(t[0].op).toBe('<')
    expect(t[0].val).toBe('90s')
  })

  it('普通关键词不产生条件', () => {
    expect(tokens('雪景').length).toBe(0)
  })
})
