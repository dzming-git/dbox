import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { comicApi } from '../api'
import { getDefaultSort } from '../utils/userSettings'
import type { Comic } from '../types'

export const useComicStore = defineStore('comic', () => {
  const comics = ref<Comic[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const pagination = ref({ limit: 24, offset: 0, total: 0 })

  const selectedLibraryId = ref<number | null>(null)
  const selectedTagId = ref<number | null>(null)
  const libraries = ref<any[]>([])
  const searchQuery = ref('')
  const sortBy = ref(getDefaultSort().sort)
  const sortOrder = ref(getDefaultSort().order)
  const viewMode = ref<'grid' | 'list'>(
    (localStorage.getItem('dplayer_comic_view_mode') as 'grid' | 'list') || 'grid'
  )

  const hasMore = computed(() => comics.value.length < pagination.value.total)

  const fetchComics = async (reset = false) => {
    loading.value = true
    error.value = null
    try {
      const currentOffset = reset ? 0 : comics.value.length
      const params: any = { limit: pagination.value.limit, offset: currentOffset }
      if (selectedLibraryId.value) params.library_id = selectedLibraryId.value
      if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
      if (sortBy.value) params.sort = sortBy.value
      if (sortOrder.value) params.order = sortOrder.value
      params.exclude_disliked = 'true'
      if (selectedTagId.value) params.tag_id = selectedTagId.value

      const res: any = await comicApi.getComics(params)
      comics.value = reset ? res.comics : [...comics.value, ...res.comics]
      pagination.value.total = res.total
      pagination.value.offset = currentOffset
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取漫画失败'
    } finally {
      loading.value = false
    }
  }

  const fetchComicsByOffset = async (offset: number) => {
    loading.value = true
    error.value = null
    try {
      const params: any = { limit: pagination.value.limit, offset }
      if (selectedLibraryId.value) params.library_id = selectedLibraryId.value
      if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
      if (sortBy.value) params.sort = sortBy.value
      if (sortOrder.value) params.order = sortOrder.value
      params.exclude_disliked = 'true'
      if (selectedTagId.value) params.tag_id = selectedTagId.value
      const res: any = await comicApi.getComics(params)
      comics.value = res.comics
      pagination.value.total = res.total
      pagination.value.offset = offset
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取漫画失败'
    } finally {
      loading.value = false
    }
  }

  const searchComics = async (q: string) => {
    searchQuery.value = q
    await fetchComics(true)
  }

  const clearSearch = async () => {
    searchQuery.value = ''
    await fetchComics(true)
  }

  const filterByLibrary = async (libraryId: number | null) => {
    selectedLibraryId.value = libraryId
    await fetchComics(true)
  }

  const filterByTag = async (tagId: number | null) => {
    selectedTagId.value = tagId
    await fetchComics(true)
  }

  const setSortBy = async (sort: string) => {
    sortBy.value = sort
    await fetchComics(true)
  }

  const setSortOrder = async (order: string) => {
    sortOrder.value = order
    await fetchComics(true)
  }

  const setViewMode = (mode: 'grid' | 'list') => {
    viewMode.value = mode
    localStorage.setItem('dplayer_comic_view_mode', mode)
  }

  // ============ URL 状态同步（与视频模式框架一致） ============
  // 将当前筛选/排序/分页状态编码为 URL query 参数
  const toQuery = () => {
    const query: Record<string, string> = {}
    if (selectedLibraryId.value) {
      query.lib = String(selectedLibraryId.value)
    }
    if (searchQuery.value.trim()) {
      query.search = searchQuery.value.trim()
    }
    if (sortBy.value && sortBy.value !== getDefaultSort().sort) {
      query.sort = sortBy.value
    }
    if (sortOrder.value && sortOrder.value !== getDefaultSort().order) {
      query.order = sortOrder.value
    }
    if (pagination.value.offset > 0) {
      query.page = String(Math.floor(pagination.value.offset / pagination.value.limit) + 1)
    }
    if (selectedTagId.value) {
      query.tag = String(selectedTagId.value)
    }
    return query
  }

  // 从 URL query 参数恢复状态（用于刷新/分享链接/浏览器前进后退）
  const initFromQuery = async (query: Record<string, string>) => {
    selectedLibraryId.value = query.lib ? (parseInt(query.lib) || null) : null
    selectedTagId.value = query.tag ? (parseInt(query.tag) || null) : null
    searchQuery.value = query.search || ''
    // 缺失的参数恢复默认值（切换模式时清空 URL，其他参数应回到默认）
    const defSort = getDefaultSort()
    sortBy.value = query.sort || defSort.sort
    sortOrder.value = query.order || defSort.order
    const page = query.page ? (parseInt(query.page) || 1) : 1
    const offset = (page - 1) * pagination.value.limit
    await fetchComicsByOffset(offset)
  }

  const interact = async (hash: string, type: 'like' | 'favorite' | 'dislike') => {
    try {
      const res: any = await comicApi.interact(hash, type)
      if (res.success) {
        const c = comics.value.find(c => c.hash === hash)
        if (c) {
          if (type === 'like') c.is_liked = res.active
          if (type === 'favorite') c.is_favorited = res.active
          if (type === 'dislike') c.is_disliked = res.active
        }
      }
      return res
    } catch (e) {
      console.error('漫画操作失败:', e)
    }
  }

  const saveProgress = async (hash: string, page: number, progress: number) => {
    try {
      await comicApi.saveProgress(hash, page, progress)
    } catch (e) {
      console.error('保存进度失败:', e)
    }
  }

  const fetchUserLibraries = async () => {
    try {
      const res: any = await comicApi.getComics({ limit: 1 })
      // libraries 通过 video 接口更全；这里从 user/libraries 取
      const vres: any = await (await import('../api')).videoApi.getLibraries()
      if (vres.success && vres.data) libraries.value = vres.data
      else libraries.value = []
    } catch {
      libraries.value = []
    }
  }

  const scanLibrary = async (libraryId: number) => {
    const res: any = await comicApi.scan(libraryId)
    return res
  }

  const scanStatus = async (libraryId: number) => {
    const res: any = await comicApi.scanStatus(libraryId)
    return res.status
  }

  return {
    comics, loading, error, pagination,
    selectedLibraryId, selectedTagId, libraries, searchQuery, sortBy, sortOrder, viewMode, hasMore,
    fetchComics, fetchComicsByOffset, searchComics, clearSearch,
    filterByLibrary, filterByTag, setSortBy, setSortOrder, setViewMode,
    interact, saveProgress, fetchUserLibraries, scanLibrary, scanStatus,
    toQuery, initFromQuery
  }
})
