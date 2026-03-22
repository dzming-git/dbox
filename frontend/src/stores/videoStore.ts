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
  const searchQuery = ref('')
  const sortBy = ref('recommended')  // 排序方式
  const sortOrder = ref('desc')  // 排序方向: asc, desc

  // 换一批功能 - 保存之前的视频列表用于撤回
  const previousVideos = ref<Video[]>([])
  
  const hasMore = computed(() => 
    pagination.value.offset + videos.value.length < pagination.value.total
  )
  
  const fetchVideos = async (reset = false) => {
    loading.value = true
    try {
      const params: any = {
        limit: pagination.value.limit,
        offset: reset ? 0 : pagination.value.offset + 1,
      }
      
      if (selectedTagId.value) {
        params.tag_id = selectedTagId.value
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
      await videoApi.likeVideo(hash)
    } catch (e) {
      console.error('点赞失败:', e)
    }
  }
  
  const favoriteVideo = async (hash: string) => {
    try {
      await videoApi.favoriteVideo(hash)
    } catch (e) {
      console.error('收藏失败:', e)
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
  
  const filterByTag = async (tagId: number | null) => {
    selectedTagId.value = tagId
    await fetchVideos(true)
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
    searchQuery,
    sortBy,
    sortOrder,
    hasMore,
    fetchVideos,
    loadMore: () => fetchVideos(false),
    fetchVideo,
    likeVideo,
    favoriteVideo,
    deleteVideo,
    updateVideo,
    fetchTags,
    createTag,
    updateTag,
    deleteTag,
    filterByTag,
    setSortBy,
    setSortOrder,
    shuffleVideos,
    undoShuffle,
    previousVideos,
    scanVideos,
    searchVideos,
    clearSearch
  }
})
