import { onMounted, onUnmounted } from 'vue'
import { API_BASE } from '../api'

/**
 * 订阅服务端任务推送（SSE），只在任务状态/进度变化时收到回调。
 *
 * 说明：
 * - 浏览器原生 EventSource 不能自定义请求头，登录态通过 URL 上的 token 传递
 *   （后端 resolve_identity 支持 ?token= 回退）；
 * - EventSource 自带断线重连，这里不额外实现重连逻辑，只在卸载时关闭；
 * - 同一页面多次订阅会各自建一条连接，因此只应在根组件订阅一次，
 *   其它组件通过共享状态消费。
 */
export function useTaskStream(onTask: (task: any) => void) {
  let es: EventSource | null = null

  const connect = () => {
    const token = localStorage.getItem('token') || ''
    if (!token) return
    const url = `${API_BASE}/api/tasks/stream?token=${encodeURIComponent(token)}`
    try {
      es = new EventSource(url)
    } catch {
      es = null
      return
    }
    es.addEventListener('task', (ev) => {
      try {
        onTask(JSON.parse((ev as MessageEvent).data))
      } catch {
        // 单条事件解析失败不影响后续推送
      }
    })
    // 错误交给 EventSource 自动重连；这里只避免控制台噪音
    es.onerror = () => {}
  }

  const close = () => {
    if (es) {
      es.close()
      es = null
    }
  }

  onMounted(connect)
  onUnmounted(close)

  return { close, reconnect: () => { close(); connect() } }
}
