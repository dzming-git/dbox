// 统一的 axios 客户端与拦截器（token 注入 / 401 静默刷新 / 跳登录）。
// 各领域 API 模块统一从本文件导入 api 实例，避免拦截器逻辑散落重复。
import axios from 'axios'

// 根据环境自动选择API地址
// 开发环境使用代理（留空，让 Vite 代理处理），生产环境使用相对路径（同域名）
const isDev = import.meta.env.DEV
const API_BASE = ''  // 统一使用相对路径，开发时由 Vite 代理处理

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器
api.interceptors.request.use(
  config => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  error => Promise.reject(error)
)

// ---- 401 自动刷新 access_token，避免登录态被无故踢出 ----
// 用 refresh_token 静默换取新 access_token；仅在刷新也失败时才清理并跳登录。
let isRefreshing = false
let pendingQueue: Array<(token: string | null) => void> = []

function subscribeTokenRefresh(cb: (token: string | null) => void) {
  pendingQueue.push(cb)
}
function onRefreshed(token: string | null) {
  pendingQueue.forEach(cb => cb(token))
  pendingQueue = []
}

async function refreshAccessToken(): Promise<string | null> {
  const refreshToken = localStorage.getItem('refresh_token')
  if (!refreshToken) return null
  try {
    // 注意：用裸 axios 调用，不经过 api 拦截器，避免对刷新接口自身递归触发刷新
    const resp = await axios.post('/api/v2/auth/refresh', { refresh_token: refreshToken }, {
      headers: { 'Content-Type': 'application/json' }
    })
    const data = resp.data
    if (data && data.success && data.data && data.data.access_token) {
      const newToken = data.data.access_token
      localStorage.setItem('token', newToken)
      try {
        const { useUserStore } = await import('../stores/userStore')
        useUserStore().setTokens(newToken, data.data.refresh_token)
      } catch {
        // 忽略 store 未就绪的情况，token 已写入 localStorage
      }
      return newToken
    }
    return null
  } catch {
    return null
  }
}

async function clearAuthAndRedirect() {
  localStorage.removeItem('token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user')
  try {
    const { useUserStore } = await import('../stores/userStore')
    useUserStore().logout()
  } catch {
    // ignore
  }
  // 关键：判断是否已在登录页要用 pathname（忽略 query）。否则登录页上的启动请求
  // （如 login_required 的 listExtensions）也会 401，再次被重定向到
  // /login?redirect=<当前带 query 的地址>，redirect 参数会层层嵌套增长，形成
  // 「/ 与 /login?redirect=… 整页互刷」的闪烁死循环，未登录时完全无法使用。
  if (window.location.pathname === '/login') {
    return
  }
  const dest = window.location.pathname + window.location.search
  window.location.href = `/login?redirect=${encodeURIComponent(dest)}`
}

// 响应拦截器
api.interceptors.response.use(
  response => response.data,
  async error => {
    const original = error.config as any
    const status = error.response?.status
    if (status === 401 && original && !original._retry) {
      const url: string = original.url || ''
      // 登录/刷新接口本身返回 401：直接清理并跳登录（不再重试，避免死循环）
      if (url.includes('/api/v2/auth/login') || url.includes('/api/v2/auth/refresh')) {
        await clearAuthAndRedirect()
        return Promise.reject(error)
      }
      // 已有刷新在进行：排队，等刷新完成后用新 token 重试
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          subscribeTokenRefresh(token => {
            if (token) {
              original._retry = true
              original.headers.Authorization = `Bearer ${token}`
              resolve(api(original))
            } else {
              reject(error)
            }
          })
        })
      }
      original._retry = true
      isRefreshing = true
      try {
        const newToken = await refreshAccessToken()
        if (newToken) {
          onRefreshed(newToken)
          original.headers.Authorization = `Bearer ${newToken}`
          return api(original)
        }
        onRefreshed(null)
        await clearAuthAndRedirect()
      } finally {
        isRefreshing = false
      }
      return Promise.reject(error)
    }
    return Promise.reject(error)
  }
)

// 响应拦截器已把返回值剥为 response.data，因此对外暴露的 api 应视为「直接返回数据」。
// 用 TypedApi 覆盖 AxiosInstance 的默认签名，消除各 store/api 中对 res.data / res.success 的类型摩擦。
type AnyPromise = Promise<any>
interface TypedApi {
  get(url: string, config?: any): AnyPromise
  post(url: string, data?: any, config?: any): AnyPromise
  put(url: string, data?: any, config?: any): AnyPromise
  delete(url: string, config?: any): AnyPromise
  patch(url: string, data?: any, config?: any): AnyPromise
}

export default api as unknown as TypedApi
export { api, API_BASE, axios }
