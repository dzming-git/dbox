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
  //
  // 关键修复：游客态（未登录）的 identity key 是 Flask session 里的随机 6 位数，
  // 浏览器关闭/清 cookie 后会变化，导致之前的 DELETE 删不到旧 key 的后端记录，
  // 于是「删了又回来」。因此游客态完全以 localStorage 为唯一真相，不读写后端。
  const init = async () => {
    const userStore = useUserStore()
    if (!userStore.isLoggedIn) {
      // 游客：只加载本地，不与后端交互，避免残留后端记录复活
      items.value = loadLocal()
      return
    }
    try {
      const res = await watchLaterApi.list()
      const serverItems: WatchLaterItem[] =
        res && res.success && Array.isArray(res.items) ? res.items : []
      const serverKeys = new Set(serverItems.map((it) => keyOf(it.type, it.id)))
      // 本地有、后端没有 -> 上传，完成首次迁移
      const localOnly = items.value.filter((it) => !serverKeys.has(keyOf(it.type, it.id)))
      if (localOnly.length) {
        await Promise.all(
          localOnly.map((it) =>
            watchLaterApi
              .add({
                type: it.type,
                id: it.id,
                title: it.title,
                thumbnail: it.thumbnail,
              })
              .catch(() => null)
          )
        )
        // 重新拉取一次，确保与后端完全一致
        const res2 = await watchLaterApi.list()
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
    // 游客态不写后端：随机 session key 会导致删除时匹配不到，数据残留后复活
    const userStore = useUserStore()
    if (!userStore.isLoggedIn) return
    try {
      await watchLaterApi.add(item)
    } catch {
      // 后端失败：保留本地状态，下次 init 不会被覆盖（以本地为准兜底）
    }
  }

  const remove = async (type: WatchLaterType, id: string) => {
    items.value = items.value.filter((it) => !(it.type === type && it.id === id))
    persistLocal(items.value)
    // 游客态不写后端，保证删除一定能删干净，不会从后端残留记录复活
    const userStore = useUserStore()
    if (!userStore.isLoggedIn) return
    try {
      await watchLaterApi.remove(type, id)
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
      await watchLaterApi.clear()
    } catch {
      // 后端失败：本地已清空，下次 init 以本地为准兜底
    }
  }

  return { items, list, count, has, add, remove, toggle, clear, keyOf, init }
})
