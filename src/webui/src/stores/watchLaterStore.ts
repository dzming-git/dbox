import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { watchLaterApi } from '../api'
import { useUserStore } from './userStore'

export type WatchLaterType = 'video' | 'gallery' | 'post' | 'text'

export interface WatchLaterItem {
  type: WatchLaterType
  id: string // 视频/图集用 hash，帖子/文本用 id
  title: string
  thumbnail?: string
  addedAt: string
}

const STORAGE_KEY = 'watchLater'

// localStorage 仅作为「未登录游客态」的本地缓存。
// 登录账号以「后端为唯一数据源」：init 直接以后端列表为准，既不读取本地残留、
// 也不把本地残留反向推回后端。这样删除操作一定作用于后端，且本地不会留存可被
// 重新上传的镜像，从根本上杜绝「删了又回来 / 始终删不掉」的僵尸复活问题。
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

function clearLocal() {
  localStorage.removeItem(STORAGE_KEY)
}

export const useWatchLaterStore = defineStore('watchLater', () => {
  // 游客态以本地缓存初始化；登录态由 init() 用服务端数据覆盖，不引入本地残留
  const items = ref<WatchLaterItem[]>(loadLocal())

  const list = computed(() =>
    [...items.value].sort((a, b) => (a.addedAt < b.addedAt ? 1 : -1))
  )

  const count = computed(() => items.value.length)

  const keyOf = (type: WatchLaterType, id: string) => `${type}:${id}`

  const has = (type: WatchLaterType, id: string) =>
    items.value.some((it) => it.type === type && it.id === id)

  // 登录态：后端为唯一数据源。直接以服务端列表覆盖内存，并清空本地镜像，
  // 杜绝本地残留被下一次 init（登出/重新登录/库重建触发）重新推回后端。
  // 游客态：只加载本地，不与后端交互。
  const init = async () => {
    const userStore = useUserStore()
    if (!userStore.isLoggedIn) {
      items.value = loadLocal()
      return
    }
    try {
      const res = await watchLaterApi.list()
      const serverItems: WatchLaterItem[] =
        res && res.success && Array.isArray(res.items) ? res.items : []
      items.value = serverItems
      clearLocal()
    } catch {
      // 网络/鉴权失败：继续使用当前内存状态，保证可用性
    }
  }

  const add = async (item: Omit<WatchLaterItem, 'addedAt'>) => {
    if (has(item.type, item.id)) return
    items.value.push({ ...item, addedAt: new Date().toISOString() })
    const userStore = useUserStore()
    // 游客态以本地为准；登录态只写后端（本地镜像已在 init 时清空且不再回写）
    if (!userStore.isLoggedIn) {
      persistLocal(items.value)
      return
    }
    try {
      await watchLaterApi.add(item)
    } catch {
      // 后端失败：保留内存状态，下次 init 以后端为准兜底
    }
  }

  const remove = async (type: WatchLaterType, id: string) => {
    items.value = items.value.filter((it) => !(it.type === type && it.id === id))
    const userStore = useUserStore()
    if (!userStore.isLoggedIn) {
      persistLocal(items.value)
      return
    }
    try {
      await watchLaterApi.remove(type, id)
    } catch {
      // 后端失败：内存已移除，下次 init 以后端为准兜底
    }
  }

  const toggle = (item: Omit<WatchLaterItem, 'addedAt'>) => {
    if (has(item.type, item.id)) remove(item.type, item.id)
    else add(item)
  }

  const clear = async () => {
    items.value = []
    const userStore = useUserStore()
    // 游客态：仅清本地镜像；登录态：本地镜像已在 init 时清空且不再回写，
    // 这里直接清空后端（其 user_key 稳定）。两种情况都以后端为最终真相。
    if (!userStore.isLoggedIn) {
      persistLocal(items.value)
    }
    try {
      await watchLaterApi.clear()
    } catch {
      // 后端失败：内存已清空，下次 init 以后端为准兜底
    }
  }

  return { items, list, count, has, add, remove, toggle, clear, keyOf, init }
})
