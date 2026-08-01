// 统一的 axios 客户端与拦截器（token 注入 / 401 静默刷新 / 跳登录）。
// 各领域 API 模块统一从本文件导入 api 实例，避免拦截器逻辑散落重复。
import axios from 'axios'

const API_BASE = '' // 统一使用相对路径，开发时由 Vite 代理处理

const api = axios.create({
  baseURL: API_BASE,
  timeout: 10000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json'
  }
})

// 请求拦截器：注入 access_token
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
    // 用裸 axios 调用，不经过 api 拦截器，避免对刷新接口自身递归触发刷新
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
  const currentPath = window.location.pathname + window.location.search
  if (currentPath !== '/login') {
    window.location.href = `/login?redirect=${encodeURIComponent(currentPath)}`
  }
}

// 响应拦截器：剥离 data 包裹，并对 401 静默刷新后重试
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

export default api
export { API_BASE }
