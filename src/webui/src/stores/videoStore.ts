import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { videoApi, tagApi } from '../api'
import type { Video, Tag } from '../types'

export const useVideoStore = defineStore('video', () => {
  const videos = ref<Video[]>([])
  const tags = ref<Tag[]>([])
  const currentVideo = ref<Video | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)
  
  const pagination = ref({
    limit: 20,
    offset: 0,
    total: 0
  })
  
  const selectedTagId = ref<number | null>(null)
  const selectedUntagged = ref(false)  // 是否仅看「未标记（待整理）」的视频
  const selectedLibraryId = ref<number | null>(null)  // 按视频库筛选，null=全部
  const libraries = ref<any[]>([])  // 当前用户可访问的视频库列表
  const searchQuery = ref('')
  const sortBy = ref('recommended')  // 排序方式
  const sortOrder = ref('desc')  // 排序方向: asc, desc
  const viewMode = ref<'grid' | 'list'>(
    (localStorage.getItem('dplayer_view_mode') as 'grid' | 'list') || 'grid'
  )  // 显示模式: grid=缩略图, list=列表


  // 换一批功能 - 保存之前的视频列表用于撤回
  const previousVideos = ref<Video[]>([])
  
  // 刷新节流：记录最后获取时间，避免短时间内重复请求
  let _lastFetchTime = 0
  const FETCH_COOLDOWN = 3 * 1000  // 3 秒冷却（缩短冷却时间）
  const hasFetchedRecently = () => Date.now() - _lastFetchTime < FETCH_COOLDOWN
  
  const hasMore = computed(() => 
    videos.value.length < pagination.value.total
  )

  // 读取"屏蔽不喜欢的视频"设置（默认开启），设置保存在 localStorage
  const getBlockDisliked = (): boolean => {
    try {
      const raw = localStorage.getItem('userSettings')
      if (raw) {
        const s = JSON.parse(raw)
        return s.blockDisliked !== false
      }
    } catch {
      // 忽略解析错误，使用默认
    }
    return true
  }
  
  const fetchVideos = async (reset = false) => {
    // 节流：如果最近刚获取过且不是强制刷新，跳过
    // 注意：reset=true 时强制刷新，不受冷却时间限制
    if (!reset && hasFetchedRecently()) return
    _lastFetchTime = Date.now()
    loading.value = true
    try {
      // reset=true: 从头开始 (offset=0)
      // reset=false: 继续加载 (offset = 已加载的视频数量)
      const currentOffset = reset ? 0 : videos.value.length
      const params: any = {
        limit: pagination.value.limit,
        offset: currentOffset,
      }
      
      if (selectedTagId.value && !selectedUntagged.value) {
        params.tag_id = selectedTagId.value
      }

      if (selectedUntagged.value) {
        params.untagged = 1
      }

      if (selectedLibraryId.value) {
        params.library_id = selectedLibraryId.value
      }

      if (searchQuery.value.trim()) {
        params.search = searchQuery.value.trim()
      }

      // 添加排序参数
      if (sortBy.value) {
        params.sort = sortBy.value
      }
      if (sortOrder.value) {
        params.order = sortOrder.value
      }

      // 默认屏蔽不喜欢的视频（设置可关闭）
      params.exclude_disliked = getBlockDisliked() ? 'true' : 'false'

      const response = await videoApi.getVideos(params) as any
      videos.value = reset ? response.videos : [...videos.value, ...response.videos]
      pagination.value.total = response.total
      pagination.value.offset = params.offset
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取视频失败'
    } finally {
      loading.value = false
    }
  }
  
  // 搜索视频
  const searchVideos = async (query: string) => {
    searchQuery.value = query
    await fetchVideos(true)
  }

  // 清除搜索
  const clearSearch = async () => {
    searchQuery.value = ''
    await fetchVideos(true)
  }

  // 根据 offset 获取视频（用于分页）
  const fetchVideosByOffset = async (offset: number) => {
    _lastFetchTime = Date.now()
    loading.value = true
    try {
      const params: any = {
        limit: pagination.value.limit,
        offset: offset,
      }

      if (selectedTagId.value && !selectedUntagged.value) {
        params.tag_id = selectedTagId.value
      }

      if (selectedUntagged.value) {
        params.untagged = 1
      }

      if (selectedLibraryId.value) {
        params.library_id = selectedLibraryId.value
      }

      if (searchQuery.value.trim()) {
        params.search = searchQuery.value.trim()
      }

      if (sortBy.value) {
        params.sort = sortBy.value
      }
      if (sortOrder.value) {
        params.order = sortOrder.value
      }

      // 默认屏蔽不喜欢的视频（设置可关闭）
      params.exclude_disliked = getBlockDisliked() ? 'true' : 'false'

      const response = await videoApi.getVideos(params) as any
      videos.value = response.videos
      pagination.value.total = response.total
      pagination.value.offset = offset
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取视频失败'
    } finally {
      loading.value = false
    }
  }

  const fetchVideo = async (hash: string) => {
    try {
      const response = await videoApi.getVideo(hash) as any
      currentVideo.value = response.video
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取视频失败'
    }
  }
  
  const likeVideo = async (hash: string) => {
    try {
      const response = await videoApi.likeVideo(hash) as any
      if (response.success) {
        // 更新视频列表中对应视频的点赞数量
        const index = videos.value.findIndex(v => v.hash === hash)
        if (index !== -1) {
          videos.value[index] = { ...videos.value[index], like_count: response.like_count, is_liked: response.liked }
        }
      }
      return response
    } catch (e) {
      console.error('点赞失败:', e)
    }
  }
  
  const favoriteVideo = async (hash: string) => {
    try {
      const response = await videoApi.favoriteVideo(hash) as any
      if (response.success) {
        // 更新视频列表中对应视频的收藏数量
        const index = videos.value.findIndex(v => v.hash === hash)
        if (index !== -1) {
          videos.value[index] = { ...videos.value[index], favorite_count: response.favorite_count, is_favorited: response.favorited }
        }
        return response
      }
    } catch (e) {
      console.error('收藏失败:', e)
    }
  }

  // 标记/取消标记不喜欢（踩）。被标记后会保留在当前列表中（避免误触无法撤回），
  // 下次刷新（fetchVideos 会带 exclude_disliked）时才不再返回该视频
  const dislikeVideo = async (hash: string) => {
    try {
      const response = await videoApi.dislikeVideo(hash) as any
      if (response && response.success) {
        const disliked = response.disliked
        const index = videos.value.findIndex(v => v.hash === hash)
        if (index !== -1) {
          videos.value[index] = { ...videos.value[index], disliked }
        }
        return response
      }
    } catch (e) {
      console.error('不喜欢操作失败:', e)
    }
  }
  
  // 删除视频
  const deleteVideo = async (hash: string, deleteFile = false) => {
    try {
      const response = await videoApi.deleteVideo(hash, deleteFile) as any
      if (response.success) {
        // 从列表中移除
        videos.value = videos.value.filter(v => v.hash !== hash)
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除视频失败'
      throw e
    }
  }
  
  // 更新视频
  const updateVideo = async (hash: string, data: Partial<Video>) => {
    try {
      const response = await videoApi.updateVideo(hash, data) as any
      if (response.success) {
        // 更新当前视频
        if (currentVideo.value && currentVideo.value.hash === hash) {
          currentVideo.value = { ...currentVideo.value, ...data }
        }
        // 更新列表中的视频
        const index = videos.value.findIndex(v => v.hash === hash)
        if (index !== -1) {
          videos.value[index] = { ...videos.value[index], ...data }
        }
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '更新视频失败'
      throw e
    }
  }
  
  const fetchTags = async () => {
    try {
      const response = await tagApi.getTags() as any
      tags.value = response.tags
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取标签失败'
    }
  }
  
  // 创建标签 - 支持多级标签
  const createTag = async (name: string, category?: string, parentId?: number) => {
    try {
      const response = await tagApi.createTag(name, category, parentId) as any
      if (response.success) {
        await fetchTags()
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '创建标签失败'
      throw e
    }
  }
  
  // 更新标签 - 支持修改父标签
  const updateTag = async (id: number, data: Partial<Tag>) => {
    try {
      const response = await tagApi.updateTag(id, data) as any
      if (response.success) {
        await fetchTags()
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '更新标签失败'
      throw e
    }
  }
  
  // 删除标签
  const deleteTag = async (id: number) => {
    try {
      const response = await tagApi.deleteTag(id) as any
      if (response.success) {
        tags.value = tags.value.filter(t => t.id !== id)
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除标签失败'
      throw e
    }
  }

  // 搜索标签 - 用于智能提示
  const searchTags = async (keyword: string, libraryId?: number) => {
    try {
      const response = await tagApi.searchTags(keyword, libraryId) as any
      if (response.success) {
        return response.tags || []
      }
      return []
    } catch (e) {
      error.value = e instanceof Error ? e.message : '搜索标签失败'
      return []
    }
  }

  const filterByTag = async (tagId: number | null) => {
    selectedTagId.value = tagId
    selectedUntagged.value = false
    await fetchVideos(true)
  }

  // 仅看未标记（待整理）的视频——与标签筛选互斥
  const filterByUntagged = async (value: boolean) => {
    selectedUntagged.value = value
    if (value) {
      selectedTagId.value = null
    }
    await fetchVideos(true)
  }

  // 按视频库筛选
  const filterByLibrary = async (libraryId: number | null) => {
    selectedLibraryId.value = libraryId
    await fetchVideos(true)
  }

  // 批量互动（点赞/收藏/不喜欢）
  const batchInteractVideos = async (hashes: string[], action: 'like' | 'favorite' | 'dislike') => {
    try {
      const response = await videoApi.batchInteract(hashes, action) as any
      if (response.success) {
        // 重新拉取以同步状态
        await fetchVideos(true)
      }
      return response
    } catch (e) {
      console.error('批量操作失败:', e)
    }
  }

  // 获取当前用户可访问的视频库列表
  const fetchUserLibraries = async () => {
    try {
      const response = await videoApi.getLibraries() as any
      if (response.success && response.data) {
        libraries.value = response.data
      } else {
        libraries.value = []
      }
    } catch (e) {
      libraries.value = []
    }
  }

  // 设置排序方式
  const setSortBy = async (sort: string) => {
    sortBy.value = sort
    await fetchVideos(true)
  }

  // 设置排序方向
  const setSortOrder = async (order: string) => {
    sortOrder.value = order
    await fetchVideos(true)
  }

  // 设置显示模式（缩略图/列表），并持久化到 localStorage
  const setViewMode = (mode: 'grid' | 'list') => {
    viewMode.value = mode
    try {
      localStorage.setItem('dplayer_view_mode', mode)
    } catch {
      // 忽略隐私模式下的写入失败
    }
  }


  // 换一批 - 重新获取视频（使用随机排序）
  const shuffleVideos = async () => {
    // 保存当前视频列表用于撤回
    previousVideos.value = [...videos.value]
    // 强制使用推荐排序（带随机）重新获取
    sortBy.value = 'recommended'
    await fetchVideos(true)
  }

  // 撤回上一次换一批
  const undoShuffle = async () => {
    if (previousVideos.value.length > 0) {
      // 恢复之前的视频列表
      videos.value = [...previousVideos.value]
      previousVideos.value = []
    }
  }

  // 将当前状态转换为 URL query 参数
  const toQuery = () => {
    const query: Record<string, string> = {}
    if (selectedTagId.value) {
      query.tag = String(selectedTagId.value)
    }
    if (selectedUntagged.value) {
      query.untagged = '1'
    }
    if (selectedLibraryId.value) {
      query.lib = String(selectedLibraryId.value)
    }
    if (searchQuery.value) {
      query.search = searchQuery.value
    }
    if (sortBy.value && sortBy.value !== 'recommended') {
      query.sort = sortBy.value
    }
    if (sortOrder.value && sortOrder.value !== 'desc') {
      query.order = sortOrder.value
    }
    if (pagination.value.offset > 0) {
      query.page = String(Math.floor(pagination.value.offset / pagination.value.limit) + 1)
    }
    return query
  }

  // 从 URL query 参数恢复状态
  const initFromQuery = async (query: Record<string, string>) => {
    if (query.untagged === '1') {
      selectedUntagged.value = true
      selectedTagId.value = null
    } else if (query.tag) {
      selectedUntagged.value = false
      selectedTagId.value = parseInt(query.tag) || null
    } else {
      selectedUntagged.value = false
      selectedTagId.value = null
    }
    if (query.lib) {
      selectedLibraryId.value = parseInt(query.lib) || null
    } else {
      selectedLibraryId.value = null
    }
    // 缺失的参数恢复默认值（切换模式时清空 URL，其他参数应回到默认）
    searchQuery.value = query.search || ''
    sortBy.value = query.sort || 'recommended'
    sortOrder.value = query.order || 'desc'
    // 根据 page 参数计算 offset（不存在则回到第 1 页）
    const page = query.page ? (parseInt(query.page) || 1) : 1
    const offset = (page - 1) * pagination.value.limit
    // 使用 offset 获取对应页数据，避免每次都重置到第 1 页
    await fetchVideosByOffset(offset)
  }

  const scanVideos = async () => {
    loading.value = true
    try {
      const response = await videoApi.scanVideos()
      if (response.success) {
        await fetchVideos(true)
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '扫描失败'
      throw e
    } finally {
      loading.value = false
    }
  }
  
  return {
    videos,
    tags,
    currentVideo,
    loading,
    error,
    pagination,
    selectedTagId,
    selectedUntagged,
    selectedLibraryId,
    libraries,
    searchQuery,
    sortBy,
    sortOrder,
    viewMode,
    hasMore,
    fetchVideos,
    fetchVideosByOffset,
    fetchVideo,
    likeVideo,
    favoriteVideo,
    dislikeVideo,
    deleteVideo,
    updateVideo,
    fetchTags,
    createTag,
    updateTag,
    deleteTag,
    searchTags,
    filterByTag,
    filterByUntagged,
    filterByLibrary,
    batchInteractVideos,
    fetchUserLibraries,
    setSortBy,
    setSortOrder,
    setViewMode,
    shuffleVideos,
    undoShuffle,
    previousVideos,
    scanVideos,
    searchVideos,
    clearSearch,
    toQuery,
    initFromQuery
  }
})
