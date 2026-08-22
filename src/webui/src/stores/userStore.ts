import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User } from '../types'
import { UserRole } from '../types'
import { libraryApi, api } from '../api'

// 从 localStorage 恢复用户信息
const getStoredUser = (): User | null => {
  try {
    const userStr = localStorage.getItem('user')
    if (userStr) {
      return JSON.parse(userStr)
    }
  } catch {
    // 解析失败，返回 null
  }
  return null
}

// 从 token 解析 role 兜底：JWT payload 含 role 字段，避免 localStorage 中
// user 对象缺失/损坏 role 时 isAdmin 误判为 false（菜单不显示）。
const getRoleFromToken = (tok: string | null): number | undefined => {
  if (!tok) return undefined
  try {
    const payload = JSON.parse(atob(tok.split('.')[1]))
    return typeof payload.role === 'number' ? payload.role : undefined
  } catch {
    return undefined
  }
}

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(getStoredUser())
  const token = ref<string | null>(localStorage.getItem('token'))
  const refreshToken = ref<string | null>(localStorage.getItem('refresh_token'))

  // 启动时从服务端刷新用户信息（确保 role 等字段是最新的）
  const refreshUserInfo = async () => {
    if (!token.value) return
    try {
      const res = await api.get('/api/v2/auth/me') as any
      if (res?.success && res?.data) {
        const freshUser: User = res.data
        user.value = freshUser
        localStorage.setItem('user', JSON.stringify(freshUser))
      }
    } catch {
      // 静默失败，保留 localStorage 中的旧值
    }
  }
  // 自动执行一次（非阻塞）
  refreshUserInfo()
  
  const isLoggedIn = computed(() => !!token.value)
  // 优先用 user.role；若 localStorage user 无 role 字段（旧格式/重排前），
  // 则从 JWT token payload 兜底取 role，确保 isAdmin 判断可靠。
  const effectiveRole = computed<number | undefined>(() => {
    const r = user.value?.role
    if (typeof r === 'number') return r
    return getRoleFromToken(token.value)
  })
  const isAdmin = computed(() =>
    effectiveRole.value !== undefined && effectiveRole.value <= UserRole.ADMIN
  )
  const isRoot = computed(() => 
    user.value?.role === UserRole.ROOT
  )
  // 当前用户可管理的资源库（含资源库管理员）。用于放开「资源库管理」入口。
  const manageableLibraries = ref<any[]>([])
  const canManageResources = computed(() => isAdmin.value || manageableLibraries.value.length > 0)

  const fetchManageableLibraries = async () => {
    if (!token.value) {
      manageableLibraries.value = []
      return
    }
    try {
      const res = await libraryApi.getLibraries() as any
      manageableLibraries.value = (res && res.success && res.data) ? res.data : []
    } catch {
      manageableLibraries.value = []
    }
  }
  

  const login = async (username: string, password: string) => {
    return { success: true }
  }
  
  const logout = () => {
    user.value = null
    token.value = null
    refreshToken.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    localStorage.removeItem('refresh_token')
  }
  
  const setUser = (userData: User, tokenValue: string, refreshTokenValue?: string) => {
    user.value = userData
    token.value = tokenValue
    localStorage.setItem('token', tokenValue)
    localStorage.setItem('user', JSON.stringify(userData))
    if (refreshTokenValue) {
      refreshToken.value = refreshTokenValue
      localStorage.setItem('refresh_token', refreshTokenValue)
    }
    fetchManageableLibraries()
  }

  // 仅更新 token（刷新接口成功后调用），避免重置用户信息
  const setTokens = (accessToken: string, refreshTokenValue?: string) => {
    token.value = accessToken
    localStorage.setItem('token', accessToken)
    if (refreshTokenValue) {
      refreshToken.value = refreshTokenValue
      localStorage.setItem('refresh_token', refreshTokenValue)
    }
  }
  
  return {
    user,
    token,
    refreshToken,
    isLoggedIn,
    isAdmin,
    isRoot,
    canManageResources,
    manageableLibraries,
    login,
    logout,
    setUser,
    setTokens,
    fetchManageableLibraries
  }
})
