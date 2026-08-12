import { reactive } from 'vue'

export type PtrMode = 'reload' | 'shuffle'
export type PtrPhase = 'idle' | 'pull' | 'ready' | 'refreshing'
export type RefreshHandler = () => void | Promise<void>

/** 触发下拉刷新的最小下拉距离（px） */
export const PTR_THRESHOLD = 64
/** 下拉指示器最大可下拉距离（px），超过后阻尼 */
export const PTR_MAX_PULL = 96
/** 刷新态最少保持时间（ms），让指示器有真实反馈 */
const PTR_MIN_DURATION = 500

const state = reactive({
  enabled: false,
  distance: 0,
  phase: 'idle' as PtrPhase,
  mode: 'reload' as PtrMode,
})

let handler: RefreshHandler | null = null

export function usePullToRefresh() {
  function setHandler(fn: RefreshHandler, mode: PtrMode = 'reload') {
    handler = fn
    state.mode = mode
    state.enabled = true
  }

  function clearHandler() {
    handler = null
    state.enabled = false
    if (state.phase !== 'refreshing') {
      state.phase = 'idle'
      state.distance = 0
    }
  }

  async function trigger() {
    if (!handler || state.phase === 'refreshing') return
    const start = Date.now()
    state.phase = 'refreshing'
    state.distance = PTR_THRESHOLD
    try {
      await handler()
    } finally {
      const elapsed = Date.now() - start
      if (elapsed < PTR_MIN_DURATION) {
        await new Promise((r) => setTimeout(r, PTR_MIN_DURATION - elapsed))
      }
      state.phase = 'idle'
      state.distance = 0
    }
  }

  return { state, setHandler, clearHandler, trigger }
}
