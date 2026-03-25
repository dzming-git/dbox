import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { User } from '../types'
import { UserRole } from '../types'

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

export const useUserStore = defineStore('user', () => {
  const user = ref<User | null>(getStoredUser())
  const token = ref<string | null>(localStorage.getItem('token'))
  
  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => 
    user.value?.role !== undefined && user.value.role >= UserRole.ADMIN
  )
  const isRoot = computed(() => 
    user.value?.role === UserRole.ROOT
  )
  
  const login = async (username: string, password: string) => {
    return { success: true }
  }
  
  const logout = () => {
    user.value = null
    token.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
  }
  
  const setUser = (userData: User, tokenValue: string) => {
    user.value = userData
    token.value = tokenValue
    localStorage.setItem('token', tokenValue)
    localStorage.setItem('user', JSON.stringify(userData))
  }
  
  return {
    user,
    token,
    isLoggedIn,
    isAdmin,
    isRoot,
    login,
    logout,
    setUser
  }
})
