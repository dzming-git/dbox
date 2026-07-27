import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export type WatchLaterType = 'video' | 'gallery' | 'post' | 'text'

export interface WatchLaterItem {
  type: WatchLaterType
  id: string // 视频/图集用 hash，帖子/文本用 id
  title: string
  thumbnail?: string
  addedAt: string
}

const STORAGE_KEY = 'watchLater'

function load(): WatchLaterItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const arr = JSON.parse(raw)
    return Array.isArray(arr) ? arr : []
  } catch {
    return []
  }
}

function persist(list: WatchLaterItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list))
}

export const useWatchLaterStore = defineStore('watchLater', () => {
  const items = ref<WatchLaterItem[]>(load())

  // 列表面板是否展开：新增条目时自动展开，方便用户看到「稍后再看」列表
  const panelOpen = ref(false)

  const list = computed(() =>
    [...items.value].sort((a, b) => (a.addedAt < b.addedAt ? 1 : -1))
  )

  const count = computed(() => items.value.length)

  const keyOf = (type: WatchLaterType, id: string) => `${type}:${id}`

  const has = (type: WatchLaterType, id: string) =>
    items.value.some((it) => it.type === type && it.id === id)

  const add = (item: Omit<WatchLaterItem, 'addedAt'>) => {
    if (has(item.type, item.id)) return
    items.value.push({ ...item, addedAt: new Date().toISOString() })
    persist(items.value)
    panelOpen.value = true
  }

  const remove = (type: WatchLaterType, id: string) => {
    items.value = items.value.filter((it) => !(it.type === type && it.id === id))
    persist(items.value)
  }

  const toggle = (item: Omit<WatchLaterItem, 'addedAt'>) => {
    if (has(item.type, item.id)) remove(item.type, item.id)
    else add(item)
  }

  const clear = () => {
    items.value = []
    persist(items.value)
  }

  return { items, list, count, has, add, remove, toggle, clear, keyOf, panelOpen }
})
