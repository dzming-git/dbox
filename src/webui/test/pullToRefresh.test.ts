import { describe, it, expect, afterEach } from 'vitest'
import { usePullToRefresh, PTR_THRESHOLD } from '../src/composables/usePullToRefresh'

describe('usePullToRefresh 组合式', () => {
  afterEach(() => {
    const { clearHandler } = usePullToRefresh()
    clearHandler()
  })

  it('setHandler 开启手势并记录模式', () => {
    const { state, setHandler } = usePullToRefresh()
    setHandler(async () => {}, 'shuffle')
    expect(state.enabled).toBe(true)
    expect(state.mode).toBe('shuffle')
  })

  it('未注册时 trigger 为空操作且不报错', async () => {
    const { state, trigger } = usePullToRefresh()
    await trigger()
    expect(state.phase).toBe('idle')
  })

  it('trigger 会执行回调并经历 refreshing -> idle', async () => {
    const { state, setHandler, trigger } = usePullToRefresh()
    let called = 0
    setHandler(() => { called++ })
    await trigger()
    expect(called).toBe(1)
    expect(state.phase).toBe('idle')
    expect(state.distance).toBe(0)
    expect(state.enabled).toBe(true)
  })

  it('refreshing 期间再次 trigger 不会重复执行', async () => {
    const { state, setHandler, trigger } = usePullToRefresh()
    let called = 0
    setHandler(async () => {
      called++
      await new Promise((r) => setTimeout(r, 10))
    })
    const p1 = trigger()
    const p2 = trigger() // 应被忽略
    await Promise.all([p1, p2])
    expect(called).toBe(1)
  })

  it('clearHandler 关闭手势', () => {
    const { state, setHandler, clearHandler } = usePullToRefresh()
    setHandler(async () => {})
    expect(state.enabled).toBe(true)
    clearHandler()
    expect(state.enabled).toBe(false)
  })

  it('阈值常量合理', () => {
    expect(PTR_THRESHOLD).toBeGreaterThan(0)
    expect(PTR_THRESHOLD).toBeLessThanOrEqual(100)
  })
})
