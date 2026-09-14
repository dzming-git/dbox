import { ref } from 'vue'
import { userStateApi } from '../api'

/** 一个保存的视图：把一组过滤条件存下来，随时一键套用 */
export interface SavedView {
  id: string
  order: number
  name: string
  /** 作用范围：目前只做视频列表 */
  scope: 'video'
  filters: {
    libraryId?: number | null
    collectionId?: number | null
    tagId?: number | null
    untagged?: boolean
    search?: string
    minDuration?: number | null
    maxDuration?: number | null
    unwatchedDays?: number | null
    sortBy?: string
    sortOrder?: string
  }
}

const NS = 'core'
const KEY = 'saved-views'

/**
 * 保存的视图：用跨设备用户状态存储（union_by_id 策略），换设备也能看到。
 * 规则由前端解释——能力边界就是列表接口支持的参数集，后端无需新增模型。
 */
export function useSavedViews() {
  const views = ref<SavedView[]>([])
  const loaded = ref(false)

  const load = async () => {
    try {
      const res: any = await userStateApi.get(NS, KEY)
      const value = res?.value
      const list: SavedView[] = Array.isArray(value)
        ? value
        : Array.isArray(value?.items)
          ? value.items
          : []
      views.value = list
        .filter((v) => v && v.id && v.name)
        .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    } catch {
      views.value = []
    } finally {
      loaded.value = true
    }
  }

  const persist = async () => {
    // union_by_id 要求每条记录带 id 与 order
    await userStateApi.put(NS, KEY, views.value, {
      strategy: 'union_by_id',
      scope: 'user',
      cap: 50,
    })
  }

  const save = async (name: string, filters: SavedView['filters']) => {
    const trimmed = (name || '').trim()
    if (!trimmed) return null
    const existing = views.value.find((v) => v.name === trimmed)
    if (existing) {
      existing.filters = { ...filters }
      await persist()
      return existing
    }
    const view: SavedView = {
      id: `view_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
      order: views.value.length ? Math.max(...views.value.map((v) => v.order ?? 0)) + 1 : 0,
      name: trimmed,
      scope: 'video',
      filters: { ...filters },
    }
    views.value = [...views.value, view]
    await persist()
    return view
  }

  const remove = async (id: string) => {
    views.value = views.value.filter((v) => v.id !== id)
    // 并集策略没有删除语义：必须显式提交一条墓碑，否则旧条目会被再次并回结果，
    // 表现为「删除成功、刷新后视图又回来了」。
    await userStateApi.put(
      NS, KEY,
      [{ id, order: Date.now(), _deleted: true }],
      { strategy: 'union_by_id', scope: 'user', cap: 50 }
    )
    // 写回剔除后的列表，保证读到的顺序与本地一致
    await persist()
  }

  return { views, loaded, load, save, remove }
}
