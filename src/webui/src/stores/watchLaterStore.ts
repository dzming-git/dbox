import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '../api'

export type WatchLaterType = 'video' | 'gallery' | 'post' | 'text'

export interface WatchLaterItem {
  type: WatchLaterType
  id: string // 视频/图集用 hash，帖子/文本用 id
  title: string
  thumbnail?: string
  addedAt: string
}

const STORAGE_KEY = 'watchLater'

function loadLocal(): WatchLaterItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function persistLocal(list: WatchLaterItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list))
}

export const useWatchLaterStore = defineStore('watchLater', () => {
  const items = ref<WatchLaterItem[]>(loadLocal())

  const list = computed(() =>
    [...items.value].sort((a, b) => (a.addedAt < b.addedAt ? 1 : -1))
  )

  const count = computed(() => items.value.length)

  const keyOf = (type: WatchLaterType, id: string) => `${type}:${id}`

  const has = (type: WatchLaterType, id: string) =>
    items.value.some((it) => it.type === type && it.id === id)

  // 从后端加载（登录账号跨设备一致）。首次同步时把本地仅有的条目上传到后端，
  // 避免登录后覆盖丢失历史数据，再以「后端为唯一数据源」为准。
  const init = async () => {
    try {
      const res = await api.get('/api/watch-later')
      const serverItems: WatchLaterItem[] =
        res && res.success && Array.isArray(res.items) ? res.items : []
      const serverKeys = new Set(serverItems.map((it) => keyOf(it.type, it.id)))
      // 本地有、后端没有 -> 上传，完成首次迁移
      const localOnly = items.value.filter((it) => !serverKeys.has(keyOf(it.type, it.id)))
      if (localOnly.length) {
        await Promise.all(
          localOnly.map((it) =>
            api
              .post('/api/watch-later', {
                type: it.type,
                id: it.id,
                title: it.title,
                thumbnail: it.thumbnail,
              })
              .catch(() => null)
          )
        )
        // 重新拉取一次，确保与后端完全一致
        const res2 = await api.get('/api/watch-later')
        if (res2 && res2.success && Array.isArray(res2.items)) {
          items.value = res2.items
          persistLocal(items.value)
          return
        }
      }
      items.value = serverItems
      persistLocal(items.value)
    } catch {
      // 网络/鉴权失败：继续使用本地缓存，保证可用性
    }
  }

  const add = async (item: Omit<WatchLaterItem, 'addedAt'>) => {
    if (has(item.type, item.id)) return
    items.value.push({ ...item, addedAt: new Date().toISOString() })
    persistLocal(items.value)
    try {
      await api.post('/api/watch-later', item)
    } catch {
      // 后端失败：保留本地状态，下次 init 不会被覆盖（以本地为准兜底）
    }
  }

  const remove = async (type: WatchLaterType, id: string) => {
    items.value = items.value.filter((it) => !(it.type === type && it.id === id))
    persistLocal(items.value)
    try {
      await api.delete(`/api/watch-later/${type}/${id}`)
    } catch {
      // 同上，本地已移除，后端失败兜底
    }
  }

  const toggle = (item: Omit<WatchLaterItem, 'addedAt'>) => {
    if (has(item.type, item.id)) remove(item.type, item.id)
    else add(item)
  }

  const clear = async () => {
    items.value = []
    persistLocal(items.value)
    try {
      await api.delete('/api/watch-later')
    } catch {
      // 后端失败：本地已清空，下次 init 以本地为准兜底
    }
  }

  return { items, list, count, has, add, remove, toggle, clear, keyOf, init }
})
