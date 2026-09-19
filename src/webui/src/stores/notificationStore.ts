import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { notificationApi } from '../api'
import type { UserNotification } from '../types'
import { useUserStore } from './userStore'

// 用户通知：后端为唯一数据源（订阅事件/下载完成等统一落点）。
// 登录态由 load() 拉取最新列表与未读数；未登录不加载。
export const useNotificationStore = defineStore('notification', () => {
  const items = ref<UserNotification[]>([])
  const unread = ref(0)

  const count = computed(() => unread.value)

  const load = async () => {
    const userStore = useUserStore()
    if (!userStore.isLoggedIn) {
      items.value = []
      unread.value = 0
      return
    }
    try {
      const res: any = await notificationApi.list({ limit: 30 })
      if (res && res.success) {
        items.value = res.items || []
        unread.value = res.unread || 0
      }
    } catch {
      // 拉取失败不阻断使用，保持当前状态
    }
  }

  const markRead = async (id: number) => {
    const it = items.value.find((n) => n.id === id)
    if (it && it.read) return
    if (it) it.read = true
    unread.value = Math.max(0, unread.value - 1)
    try {
      await notificationApi.markRead(id)
    } catch {
      // 后端失败：内存已标记，下次 load 以后端为准兜底
    }
  }

  const markAllRead = async () => {
    items.value.forEach((n) => (n.read = true))
    unread.value = 0
    try {
      await notificationApi.markAllRead()
    } catch {
      // 后端失败：内存已清空，下次 load 以后端为准兜底
    }
  }

  return { items, unread, count, load, markRead, markAllRead }
})
