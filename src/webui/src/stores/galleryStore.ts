import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { galleryApi } from '../api'
import { getDefaultSort } from '../utils/userSettings'
import type { Gallery } from '../types'

export const useGalleryStore = defineStore('gallery', () => {
  const galleries = ref<Gallery[]>([])
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
    (localStorage.getItem('dplayer_gallery_view_mode') as 'grid' | 'list') || 'grid'
  )

  const hasMore = computed(() => galleries.value.length < pagination.value.total)

  const fetchGallerys = async (reset = false) => {
    loading.value = true
    error.value = null
    try {
      const currentOffset = reset ? 0 : galleries.value.length
      const params: any = { limit: pagination.value.limit, offset: currentOffset }
      if (selectedLibraryId.value) params.library_id = selectedLibraryId.value
      if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
      if (sortBy.value) params.sort = sortBy.value
      if (sortOrder.value) params.order = sortOrder.value
      params.exclude_disliked = 'true'
      if (selectedTagId.value) params.tag_id = selectedTagId.value

      const res: any = await galleryApi.getGallerys(params)
      galleries.value = reset ? res.galleries : [...galleries.value, ...res.galleries]
      pagination.value.total = res.total
      pagination.value.offset = currentOffset
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取图集失败'
    } finally {
      loading.value = false
    }
  }

  const fetchGallerysByOffset = async (offset: number) => {
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
      const res: any = await galleryApi.getGallerys(params)
      galleries.value = res.galleries
      pagination.value.total = res.total
      pagination.value.offset = offset
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取图集失败'
    } finally {
      loading.value = false
    }
  }

  const searchGallerys = async (q: string) => {
    searchQuery.value = q
    await fetchGallerys(true)
  }

  const clearSearch = async () => {
    searchQuery.value = ''
    await fetchGallerys(true)
  }

  const filterByLibrary = async (libraryId: number | null) => {
    selectedLibraryId.value = libraryId
    await fetchGallerys(true)
  }

  const filterByTag = async (tagId: number | null) => {
    selectedTagId.value = tagId
    await fetchGallerys(true)
  }

  const setSortBy = async (sort: string) => {
    sortBy.value = sort
    await fetchGallerys(true)
  }

  const setSortOrder = async (order: string) => {
    sortOrder.value = order
    await fetchGallerys(true)
  }

  const setViewMode = (mode: 'grid' | 'list') => {
    viewMode.value = mode
    localStorage.setItem('dplayer_gallery_view_mode', mode)
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
    await fetchGallerysByOffset(offset)
  }

  // 删除图集后从缓存列表移除，避免返回列表页时仍显示已删除项（无需手动刷新）
  const removeGallery = (hash: string) => {
    const idx = galleries.value.findIndex(c => c.hash === hash)
    if (idx !== -1) {
      galleries.value.splice(idx, 1)
      if (pagination.value.total > 0) pagination.value.total -= 1
    }
  }

  const interact = async (hash: string, type: 'like' | 'favorite' | 'dislike') => {
    try {
      const res: any = await galleryApi.interact(hash, type)
      if (res.success) {
        const c = galleries.value.find(c => c.hash === hash)
        if (c) {
          if (type === 'like') c.is_liked = res.active
          if (type === 'favorite') c.is_favorited = res.active
          if (type === 'dislike') c.is_disliked = res.active
        }
      }
      return res
    } catch (e) {
      console.error('图集操作失败:', e)
    }
  }

  const saveProgress = async (hash: string, page: number, progress: number) => {
    try {
      await galleryApi.saveProgress(hash, page, progress)
    } catch (e) {
      console.error('保存进度失败:', e)
    }
  }

  const fetchUserLibraries = async () => {
    try {
      const res: any = await galleryApi.getGallerys({ limit: 1 })
      // libraries 通过 video 接口更全；这里从 user/libraries 取
      const vres: any = await (await import('../api')).videoApi.getLibraries()
      if (vres.success && vres.data) libraries.value = vres.data
      else libraries.value = []
    } catch {
      libraries.value = []
    }
  }

  const scanLibrary = async (libraryId: number) => {
    const res: any = await galleryApi.scan(libraryId)
    return res
  }

  const scanStatus = async (libraryId: number) => {
    const res: any = await galleryApi.scanStatus(libraryId)
    return res.status
  }

  return {
    galleries, loading, error, pagination,
    selectedLibraryId, selectedTagId, libraries, searchQuery, sortBy, sortOrder, viewMode, hasMore,
    fetchGallerys, fetchGallerysByOffset, searchGallerys, clearSearch,
    filterByLibrary, filterByTag, setSortBy, setSortOrder, setViewMode,
    interact, saveProgress, fetchUserLibraries, scanLibrary, scanStatus,
    removeGallery,
    toQuery, initFromQuery
  }
})
