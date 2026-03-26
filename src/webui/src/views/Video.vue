<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import { tagApi } from '../api'
import type { Video, Tag } from '../types'

const route = useRoute()
const router = useRouter()
const videoStore = useVideoStore()

// 检查当前用户是否为管理员
const isAdmin = computed(() => {
  const role = localStorage.getItem('userRole')
  return role === '2' || role === '3'  // ADMIN=2, ROOT=3
})

const video = ref<Video | null>(null)
const loading = ref(true)
const isFavorited = ref(false)
const isLiked = ref(false)
const isDisliked = ref(false)
const isWatchLater = ref(false)
const videoPlayer = ref<HTMLVideoElement | null>(null)
const isPlaying = ref(false)
const currentTime = ref(0)
const duration = ref(0)
const volume = ref(1)
const isFullscreen = ref(false)

const videoHash = computed(() => route.params.hash as string)

// 共享观看相关状态
const shareCode = ref<string>('')
const sharedSession = ref<any>(null)
const isSharedMode = ref(false)
const isCreator = ref(false)
const showShareDialog = ref(false)
const shareUrl = ref('')
const syncInterval = ref<number | null>(null)
const lastSyncTime = ref(0)

// 视频源URL - 使用后端返回的 url 字段（/api/videos/{id}/play），拼接 token 用于认证
const videoUrl = computed(() => {
  const url = video.value?.url || ''
  if (!url) return ''
  const token = localStorage.getItem('token')
  return token ? `${url}?token=${token}` : url
})

onMounted(async () => {
  // 先检查是否是共享链接访问
  await checkSharedLink()
  
  if (videoHash.value) {
    try {
      const response = await videoStore.fetchVideo(videoHash.value)
      if (response && response.video) {
        video.value = response.video
        // 增加观看次数
        await incrementViewCount()
        // 记录观看历史
        await addToHistory()
        // 从localStorage加载点赞和收藏状态
        loadUserInteractions()
      }
    } catch (error) {
      console.error('Failed to load video:', error)
    } finally {
      loading.value = false
    }
  }
})

// 从localStorage加载用户交互状态
const loadUserInteractions = () => {
  if (!video.value) return
  const likedVideos = JSON.parse(localStorage.getItem('likedVideos') || '[]')
  const dislikedVideos = JSON.parse(localStorage.getItem('dislikedVideos') || '[]')
  const favoritedVideos = JSON.parse(localStorage.getItem('favoritedVideos') || '[]')
  const watchLaterVideos = JSON.parse(localStorage.getItem('watchLaterVideos') || '[]')
  isLiked.value = likedVideos.includes(video.value.hash)
  isDisliked.value = dislikedVideos.includes(video.value.hash)
  isFavorited.value = favoritedVideos.includes(video.value.hash)
  isWatchLater.value = watchLaterVideos.includes(video.value.hash)
}

// 保存点赞状态到localStorage
const saveLikeStatus = () => {
  if (!video.value) return
  const likedVideos = JSON.parse(localStorage.getItem('likedVideos') || '[]')
  if (isLiked.value) {
    if (!likedVideos.includes(video.value.hash)) {
      likedVideos.push(video.value.hash)
    }
  } else {
    const index = likedVideos.indexOf(video.value.hash)
    if (index > -1) likedVideos.splice(index, 1)
  }
  localStorage.setItem('likedVideos', JSON.stringify(likedVideos))
}

// 保存收藏状态到localStorage
const saveFavoriteStatus = () => {
  if (!video.value) return
  const favoritedVideos = JSON.parse(localStorage.getItem('favoritedVideos') || '[]')
  const favorites = JSON.parse(localStorage.getItem('favorites') || '[]')
  
  if (isFavorited.value) {
    if (!favoritedVideos.includes(video.value.hash)) {
      favoritedVideos.push(video.value.hash)
    }
    // 添加到收藏列表
    if (!favorites.find((f: any) => f.hash === video.value!.hash)) {
      favorites.push({
        hash: video.value.hash,
        title: video.value.title,
        thumbnail: video.value.thumbnail,
        duration: video.value.duration,
        favorited_at: new Date().toISOString()
      })
    }
  } else {
    const index = favoritedVideos.indexOf(video.value.hash)
    if (index > -1) favoritedVideos.splice(index, 1)
    // 从收藏列表移除
    const favIndex = favorites.findIndex((f: any) => f.hash === video.value!.hash)
    if (favIndex > -1) favorites.splice(favIndex, 1)
  }
  
  localStorage.setItem('favoritedVideos', JSON.stringify(favoritedVideos))
  localStorage.setItem('favorites', JSON.stringify(favorites))
}

// 保存踩状态到localStorage
const saveDislikeStatus = () => {
  if (!video.value) return
  const dislikedVideos = JSON.parse(localStorage.getItem('dislikedVideos') || '[]')
  if (isDisliked.value) {
    if (!dislikedVideos.includes(video.value.hash)) {
      dislikedVideos.push(video.value.hash)
    }
  } else {
    const index = dislikedVideos.indexOf(video.value.hash)
    if (index > -1) dislikedVideos.splice(index, 1)
  }
  localStorage.setItem('dislikedVideos', JSON.stringify(dislikedVideos))
}

// 保存稍后看状态到localStorage
const saveWatchLaterStatus = () => {
  if (!video.value) return
  const watchLaterVideos = JSON.parse(localStorage.getItem('watchLaterVideos') || '[]')
  const watchLaterList = JSON.parse(localStorage.getItem('watchLater') || '[]')
  
  if (isWatchLater.value) {
    if (!watchLaterVideos.includes(video.value.hash)) {
      watchLaterVideos.push(video.value.hash)
    }
    // 添加到稍后看列表
    if (!watchLaterList.find((v: any) => v.hash === video.value!.hash)) {
      watchLaterList.push({
        hash: video.value.hash,
        title: video.value.title,
        thumbnail: video.value.thumbnail,
        duration: video.value.duration,
        added_at: new Date().toISOString()
      })
    }
  } else {
    const index = watchLaterVideos.indexOf(video.value.hash)
    if (index > -1) watchLaterVideos.splice(index, 1)
    // 从稍后看列表移除
    const wlIndex = watchLaterList.findIndex((v: any) => v.hash === video.value!.hash)
    if (wlIndex > -1) watchLaterList.splice(wlIndex, 1)
  }
  
  localStorage.setItem('watchLaterVideos', JSON.stringify(watchLaterVideos))
  localStorage.setItem('watchLater', JSON.stringify(watchLaterList))
}

// 添加到观看历史
const addToHistory = () => {
  if (!video.value) return
  const history = JSON.parse(localStorage.getItem('watchHistory') || '[]')
  const existingIndex = history.findIndex((h: any) => h.hash === video.value!.hash)
  
  const historyItem = {
    hash: video.value.hash,
    title: video.value.title,
    thumbnail: video.value.thumbnail,
    duration: video.value.duration,
    progress: 0,
    watched_at: new Date().toISOString()
  }
  
  if (existingIndex > -1) {
    history.splice(existingIndex, 1)
  }
  history.unshift(historyItem)
  
  // 限制历史记录数量
  if (history.length > 100) history.pop()
  
  localStorage.setItem('watchHistory', JSON.stringify(history))
}

// 定期保存观看进度
const saveWatchProgress = () => {
  if (!video.value || !videoPlayer.value) return
  const history = JSON.parse(localStorage.getItem('watchHistory') || '[]')
  const index = history.findIndex((h: any) => h.hash === video.value!.hash)
  if (index > -1) {
    history[index].progress = videoPlayer.value.currentTime
    history[index].duration = videoPlayer.value.duration || video.value.duration
    localStorage.setItem('watchHistory', JSON.stringify(history))
  }
}

// 增加观看次数
const incrementViewCount = async () => {
  try {
    // 调用API增加观看次数
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    await fetch(`/api/video/${videoHash.value}/view`, { method: 'POST', headers })
  } catch (e) {
    console.error('增加观看次数失败:', e)
  }
}

const handleLike = async () => {
  if (!video.value) return
  isLiked.value = !isLiked.value
  if (isLiked.value) {
    video.value.like_count++
  } else {
    video.value.like_count--
  }
  saveLikeStatus()
  await videoStore.likeVideo(video.value.hash)
}

const handleFavorite = async () => {
  if (!video.value) return
  isFavorited.value = !isFavorited.value
  saveFavoriteStatus()
  await videoStore.favoriteVideo(video.value.hash)
  // 显示提示
  const message = isFavorited.value ? '已添加到收藏' : '已取消收藏'
  showToast(message)
}

const handleDislike = async () => {
  if (!video.value) return
  // 踩和点赞互斥：如果当前是点赞状态，先取消点赞
  if (isLiked.value) {
    isLiked.value = false
    video.value.like_count--
    saveLikeStatus()
  }
  isDisliked.value = !isDisliked.value
  saveDislikeStatus()
  // 显示提示
  const message = isDisliked.value ? '我不喜欢这个视频' : '已取消踩'
  showToast(message)
}

const handleWatchLater = async () => {
  if (!video.value) return
  isWatchLater.value = !isWatchLater.value
  saveWatchLaterStatus()
  // 显示提示
  const message = isWatchLater.value ? '已添加到稍后看' : '已从稍后看移除'
  showToast(message)
}

// 提示消息
const toastMessage = ref('')
const showToastFlag = ref(false)
const showToast = (message: string) => {
  toastMessage.value = message
  showToastFlag.value = true
  setTimeout(() => {
    showToastFlag.value = false
  }, 2000)
}

const goBack = () => {
  router.back()
}

// 播放控制
const togglePlay = () => {
  if (!videoPlayer.value) return
  if (isPlaying.value) {
    videoPlayer.value.pause()
  } else {
    videoPlayer.value.play()
  }
}

const onPlay = () => {
  isPlaying.value = true
  // 共享模式下立即同步播放状态
  if (isSharedMode.value && shareCode.value && videoPlayer.value) {
    lastSyncedPlaying.value = true
    lastSyncedTime.value = videoPlayer.value.currentTime
    // 立即同步，强制发送
    syncPlaybackState(true)
  }
}

const onPause = () => {
  isPlaying.value = false
  // 共享模式下立即同步播放状态
  if (isSharedMode.value && shareCode.value && videoPlayer.value) {
    lastSyncedPlaying.value = false
    lastSyncedTime.value = videoPlayer.value.currentTime
    // 立即同步，强制发送
    syncPlaybackState(true)
  }
}

const onSeeked = () => {
  // 用户拖动进度条或键盘操作后立即同步
  if (isSharedMode.value && shareCode.value && videoPlayer.value) {
    lastSyncedTime.value = videoPlayer.value.currentTime
    lastSyncedPlaying.value = isPlaying.value
    // 立即同步，强制发送
    syncPlaybackState(true)
  }
}

const onTimeUpdate = () => {
  if (!videoPlayer.value) return
  currentTime.value = videoPlayer.value.currentTime
  // 每5秒保存一次观看进度
  if (Math.floor(currentTime.value) % 5 === 0) {
    saveWatchProgress()
  }
}

const onLoadedMetadata = () => {
  if (!videoPlayer.value) return
  // 多种方式获取duration，确保兼容性
  if (videoPlayer.value.duration && !isNaN(videoPlayer.value.duration) && videoPlayer.value.duration !== Infinity) {
    duration.value = videoPlayer.value.duration
  }
}

// 额外监听durationchange事件，解决部分移动端兼容性问题
const onDurationChange = () => {
  if (!videoPlayer.value) return
  if (videoPlayer.value.duration && !isNaN(videoPlayer.value.duration) && videoPlayer.value.duration !== Infinity) {
    duration.value = videoPlayer.value.duration
  }
}

const seek = (event: Event) => {
  const target = event.target as HTMLInputElement
  if (videoPlayer.value) {
    videoPlayer.value.currentTime = parseFloat(target.value)
    // 共享模式下同步播放进度
    if (isSharedMode.value && shareCode.value) {
      syncPlaybackState()
    }
  }
}

const setVolume = (event: Event) => {
  const target = event.target as HTMLInputElement
  volume.value = parseFloat(target.value)
  if (videoPlayer.value) {
    videoPlayer.value.volume = volume.value
  }
}

const toggleFullscreen = () => {
  if (!videoPlayer.value) return
  if (!document.fullscreenElement) {
    videoPlayer.value.requestFullscreen()
    isFullscreen.value = true
  } else {
    document.exitFullscreen()
    isFullscreen.value = false
  }
}

// 格式化时长
const formatDuration = (seconds: number): string => {
  if (!seconds || isNaN(seconds)) return '00:00'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

// 下载视频
const handleDownload = async () => {
  if (!video.value) return
  try {
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    await fetch(`/api/video/${video.value.hash}/download`, { method: 'POST', headers })
    // 创建下载链接
    const link = document.createElement('a')
    link.href = videoUrl.value
    link.download = video.value.title + '.mp4'
    link.click()
  } catch (e) {
    console.error('下载失败:', e)
  }
}

// 分享视频
const handleShare = () => {
  if (!video.value) return
  const shareUrl = `${window.location.origin}/video/${video.value.hash}`
  navigator.clipboard.writeText(shareUrl)
  showToast('链接已复制到剪贴板')
}

// ========== 共享观看功能 ==========

// 创建共享观看会话
const createSharedWatchSession = async () => {
  if (!video.value) return
  
  try {
    const token = localStorage.getItem('token')
    if (!token) {
      showToast('请先登录')
      return
    }
    
    const response = await fetch('/api/shared-watch/create', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ video_hash: video.value.hash })
    })
    
    const data = await response.json()
    
    if (data.success) {
      shareCode.value = data.share_code
      shareUrl.value = `${window.location.origin}/shared/${data.share_code}`
      isSharedMode.value = true
      isCreator.value = true
      showShareDialog.value = true
      startSyncLoop()
      showToast('共享观看链接已创建')
    } else {
      showToast(data.message || '创建失败')
    }
  } catch (e) {
    console.error('创建共享观看失败:', e)
    showToast('创建失败')
  }
}

// 加入共享观看会话
const joinSharedWatchSession = async (code: string) => {
  try {
    const token = localStorage.getItem('token')
    if (!token) {
      showToast('请先登录')
      return false
    }
    
    const response = await fetch(`/api/shared-watch/${code}/join`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    
    const data = await response.json()
    
    if (data.success) {
      shareCode.value = code
      isSharedMode.value = true
      isCreator.value = data.is_creator
      sharedSession.value = data.session
      
      // 同步到当前播放进度
      if (videoPlayer.value && data.session.current_time > 0) {
        videoPlayer.value.currentTime = data.session.current_time
      }
      if (data.session.is_playing && videoPlayer.value) {
        videoPlayer.value.play()
      } else if (videoPlayer.value) {
        videoPlayer.value.pause()
      }
      
      startSyncLoop()
      showToast('已加入共享观看')
      return true
    } else {
      showToast(data.message || '加入失败')
      return false
    }
  } catch (e) {
    console.error('加入共享观看失败:', e)
    showToast('加入失败')
    return false
  }
}

// 检查是否是共享链接访问
const checkSharedLink = async () => {
  const path = window.location.pathname
  const match = path.match(/^\/shared\/([a-zA-Z0-9]+)$/)
  
  if (match) {
    const code = match[1]
    
    // 先获取会话信息（无需登录）
    try {
      const infoResponse = await fetch(`/api/shared-watch/${code}/info`)
      const infoData = await infoResponse.json()
      
      if (!infoData.success || !infoData.is_shared) {
        showToast(infoData.message || '链接已失效')
        router.push('/')
        return
      }
      
      // 跳转到视频页面
      router.push(`/video/${infoData.video_hash}`)
      
      // 尝试加入会话
      const token = localStorage.getItem('token')
      if (token) {
        await joinSharedWatchSession(code)
      } else {
        showToast('请先登录以加入共享观看')
      }
    } catch (e) {
      console.error('检查共享链接失败:', e)
      router.push('/')
    }
  }
}

// 开始同步循环
const startSyncLoop = () => {
  if (syncInterval.value) return

  // 每500ms同步一次（从2秒降低到500ms，减少延迟）
  syncInterval.value = window.setInterval(async () => {
    if (!isSharedMode.value || !shareCode.value) return

    // 同步本地播放状态到服务器
    if (videoPlayer.value) {
      await syncPlaybackState()
    }

    // 获取远程播放状态
    await fetchPlaybackState()
  }, 500)
}

// 停止同步循环
const stopSyncLoop = () => {
  if (syncInterval.value) {
    clearInterval(syncInterval.value)
    syncInterval.value = null
  }
}

// 同步播放状态到服务器
const lastSyncedTime = ref(0)
const lastSyncedPlaying = ref(false)

const syncPlaybackState = async (force = false) => {
  if (!shareCode.value || !videoPlayer.value) return

  const token = localStorage.getItem('token')
  if (!token) return

  // 只在状态变化时才同步（时间差>1秒或播放状态改变），除非强制同步
  const timeDiff = Math.abs(videoPlayer.value.currentTime - lastSyncedTime.value)
  const playingChanged = isPlaying.value !== lastSyncedPlaying.value

  if (!force && timeDiff < 1 && !playingChanged) {
    return // 没有显著变化，跳过同步
  }

  try {
    await fetch(`/api/shared-watch/${shareCode.value}/sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        current_time: videoPlayer.value.currentTime,
        is_playing: isPlaying.value,
        timestamp: Date.now() // 添加时间戳，用于补偿网络延迟
      })
    })

    lastSyncedTime.value = videoPlayer.value.currentTime
    lastSyncedPlaying.value = isPlaying.value
    lastSyncTime.value = videoPlayer.value.currentTime
  } catch (e) {
    console.error('同步播放状态失败:', e)
  }
}

// 获取远程播放状态
const fetchPlaybackState = async () => {
  if (!shareCode.value || !videoPlayer.value) return
  
  const token = localStorage.getItem('token')
  if (!token) return
  
  try {
    const response = await fetch(`/api/shared-watch/${shareCode.value}/state`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    
    const data = await response.json()
    
    if (data.success) {
      // 同步播放进度（只在差异较大时跳转）
      const timeDiff = Math.abs(videoPlayer.value.currentTime - data.current_time)
      if (timeDiff > 3) {
        videoPlayer.value.currentTime = data.current_time
      }
      
      // 同步播放/暂停状态
      if (data.is_playing && !isPlaying.value) {
        videoPlayer.value.play()
      } else if (!data.is_playing && isPlaying.value) {
        videoPlayer.value.pause()
      }
    }
  } catch (e) {
    console.error('获取播放状态失败:', e)
  }
}

// 结束共享观看会话
const endSharedWatchSession = async () => {
  if (!shareCode.value) return
  
  const token = localStorage.getItem('token')
  if (!token) return
  
  try {
    await fetch(`/api/shared-watch/${shareCode.value}/end`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    
    stopSyncLoop()
    isSharedMode.value = false
    shareCode.value = ''
    shareUrl.value = ''
    sharedSession.value = null
    showToast('共享观看已结束')
  } catch (e) {
    console.error('结束共享观看失败:', e)
  }
}

// 复制共享链接
const copyShareUrl = () => {
  navigator.clipboard.writeText(shareUrl.value)
  showToast('链接已复制到剪贴板')
}

// 页面卸载时停止同步
onUnmounted(() => {
  stopSyncLoop()
})

// 编辑视频
const isEditing = ref(false)
const editTitle = ref('')
const editDescription = ref('')
const editPriority = ref(0)
const editTags = ref('')

// 标签智能提示
const tagSuggestions = ref<Tag[]>([])
const showTagSuggestions = ref(false)
const tagInputRef = ref<HTMLInputElement | null>(null)

// 搜索标签 - 根据视频所在视频库筛选
const searchTags = async (keyword: string) => {
  if (!keyword.trim()) {
    tagSuggestions.value = []
    return
  }

  try {
    // 传递视频的 library_id 来筛选该视频库的标签
    const libraryId = video.value?.library_id
    const response = await tagApi.searchTags(keyword, libraryId || undefined) as any
    if (response.success) {
      // 只显示与当前视频同一视频库的标签
      tagSuggestions.value = response.tags || []
    }
  } catch (e) {
    console.error('搜索标签失败:', e)
  }
}

// 标签输入处理
const onTagInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  const value = target.value

  // 获取最后一个标签（当前正在输入的）
  const tags = value.split(',').map(t => t.trim()).filter(t => t)
  const currentTag = tags[tags.length - 1]

  if (currentTag) {
    searchTags(currentTag)
    showTagSuggestions.value = true
  } else {
    tagSuggestions.value = []
    showTagSuggestions.value = false
  }
}

// 选择标签建议
const selectTagSuggestion = (tag: Tag) => {
  const tags = editTags.value.split(',').map(t => t.trim()).filter(t => t)
  tags[tags.length - 1] = tag.path  // 使用完整路径
  editTags.value = tags.join(', ')
  showTagSuggestions.value = false
  tagSuggestions.value = []
}

// 隐藏建议框
const hideTagSuggestions = () => {
  setTimeout(() => {
    showTagSuggestions.value = false
  }, 200)
}

const startEdit = () => {
  if (!video.value) return
  editTitle.value = video.value.title
  editDescription.value = video.value.description || ''
  editPriority.value = video.value.priority || 0
  // 使用完整路径作为标签值
  editTags.value = video.value.tags?.map(t => t.path || t.name).join(', ') || ''
  isEditing.value = true
}

const cancelEdit = () => {
  isEditing.value = false
  tagSuggestions.value = []
  showTagSuggestions.value = false
}

const saveEdit = async () => {
  if (!video.value) return

  try {
    // 先保存基本信息
    await videoStore.updateVideo(video.value.hash, {
      title: editTitle.value,
      description: editDescription.value,
      priority: editPriority.value
    })

    // 保存标签 - 解析输入的标签路径
    const tagPaths = editTags.value.split(',').map(t => t.trim()).filter(t => t)

    // 调用专门的标签设置 API
    const token = localStorage.getItem('token')
    if (token && tagPaths.length > 0) {
      await fetch(`/api/video/${video.value.hash}/tags`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ tags: tagPaths })
      })
    }

    // 重新获取视频信息以更新标签显示
    const response = await videoStore.fetchVideo(video.value.hash)
    if (response && response.video) {
      video.value = response.video
    }

    isEditing.value = false
  } catch (e) {
    alert('保存失败')
  }
}

// 删除视频
const showDeleteConfirm = ref(false)
const deleteFileOption = ref(false)  // 是否同时删除文件

const confirmDelete = () => {
  deleteFileOption.value = false
  showDeleteConfirm.value = true
}

const handleDelete = async () => {
  if (!video.value) return

  try {
    await videoStore.deleteVideo(video.value.hash, deleteFileOption.value)
    router.push('/')
  } catch (e) {
    alert('删除失败')
  }
}
</script>

<template>
  <div class="video-page">
    <!-- 返回按钮 -->
    <button class="back-btn" @click="goBack">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      返回
    </button>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container" data-testid="video-loading">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 视频内容 -->
    <div v-else-if="video" class="video-content">
      <!-- 视频播放器区域 -->
      <div class="player-section">
        <div class="video-player-container" data-testid="video-player">
          <video
            ref="videoPlayer"
            :src="videoUrl"
            class="video-element"
            @play="onPlay"
            @pause="onPause"
            @seeked="onSeeked"
            @timeupdate="onTimeUpdate"
            @loadedmetadata="onLoadedMetadata"
            @durationchange="onDurationChange"
            preload="metadata"
            controls
          ></video>
        </div>

        <!-- 播放器控制栏 -->
        <div class="player-controls">
          <button class="control-btn" @click="togglePlay" data-testid="play-pause-btn">
            <svg v-if="!isPlaying" width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
              <path d="M8 5v14l11-7z"/>
            </svg>
            <svg v-else width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
              <path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>
            </svg>
          </button>

          <div class="progress-bar">
            <span class="time">{{ formatDuration(currentTime) }}</span>
            <input
              type="range"
              :value="currentTime"
              :max="duration"
              @input="seek"
              class="seek-slider"
              data-testid="progress-bar"
            />
            <span class="time">{{ formatDuration(duration) }}</span>
          </div>

          <div class="volume-control" data-testid="volume-control">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
            </svg>
            <input
              type="range"
              :value="volume"
              min="0"
              max="1"
              step="0.1"
              @input="setVolume"
              class="volume-slider"
            />
          </div>

          <button class="control-btn" @click="toggleFullscreen" data-testid="fullscreen-button">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
              <path d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/>
            </svg>
          </button>
        </div>
      </div>

      <!-- 视频信息区域 -->
      <div class="video-info-section">
        <!-- 编辑模式 -->
        <div v-if="isEditing" class="edit-form" data-testid="video-edit-form">
          <div class="form-group">
            <label>视频标题</label>
            <input 
              v-model="editTitle" 
              type="text" 
              data-testid="video-title-input"
              placeholder="输入视频标题"
            />
          </div>
          <div class="form-group">
            <label>视频描述</label>
            <textarea 
              v-model="editDescription" 
              rows="4"
              data-testid="video-description-input"
              placeholder="输入视频描述"
            ></textarea>
          </div>
          <div class="form-group">
            <label>优先级 (0-100)</label>
            <input 
              v-model.number="editPriority" 
              type="number" 
              min="0" 
              max="100"
              data-testid="video-priority-input"
            />
          </div>
          <div class="form-group">
            <label>标签 (用逗号分隔，输入时自动匹配已有标签)</label>
            <div class="tag-input-wrapper">
              <input
                ref="tagInputRef"
                v-model="editTags"
                type="text"
                data-testid="tag-selector"
                placeholder="输入标签关键词，系统会自动匹配该视频库中的已有标签"
                @input="onTagInput"
                @blur="hideTagSuggestions"
              />
              <!-- 标签智能提示下拉框 -->
              <div v-if="showTagSuggestions && tagSuggestions.length > 0" class="tag-suggestions">
                <div
                  v-for="tag in tagSuggestions"
                  :key="tag.id"
                  class="tag-suggestion-item"
                  @mousedown="selectTagSuggestion(tag)"
                >
                  <span class="suggestion-path">{{ tag.path }}</span>
                </div>
              </div>
            </div>
          </div>
          <div class="form-actions">
            <button class="btn-secondary" @click="cancelEdit" data-testid="cancel-button">取消</button>
            <button class="btn-primary" @click="saveEdit" data-testid="save-button">保存</button>
          </div>
        </div>

        <!-- 查看模式 -->
        <template v-else>
          <div class="video-title-row">
            <h1 class="video-title" data-testid="video-title">{{ video.title }}</h1>
          </div>

          <div class="video-meta">
            <span class="meta-item" data-testid="view-count">{{ video.view_count }} 次观看</span>
            <span class="meta-item">{{ formatDuration(video.duration || 0) }}</span>
            <span class="meta-item" v-if="video.created_at">{{ new Date(video.created_at).toLocaleDateString() }}</span>
            <span class="meta-item" v-if="video.priority > 0">优先级: {{ video.priority }}</span>
          </div>

          <p class="video-description" data-testid="video-description">
            {{ video.description || '暂无描述' }}
          </p>

          <!-- 标签 -->
          <div class="video-tags" data-testid="video-tags" v-if="video.tags && video.tags.length > 0">
            <span v-for="tag in video.tags" :key="tag.id" class="tag-badge">
              {{ tag.name }}
            </span>
          </div>

          <!-- 视频下方交互按钮 -->
          <div class="interaction-bar">
            <!-- 第一行：互动按钮 -->
            <div class="interaction-buttons">
              <!-- 点赞 -->
              <button
                class="interact-btn like-btn"
                :class="{ active: isLiked }"
                @click="handleLike"
                data-testid="like-button"
              >
                <div class="btn-icon">
                  <svg v-if="!isLiked" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                  </svg>
                  <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                  </svg>
                </div>
                <span class="btn-label">{{ video.like_count || 0 }}</span>
              </button>

              <!-- 收藏 -->
              <button
                class="interact-btn favorite-btn"
                :class="{ active: isFavorited }"
                @click="handleFavorite"
                data-testid="favorite-button"
              >
                <div class="btn-icon">
                  <svg v-if="!isFavorited" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
                  </svg>
                  <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
                  </svg>
                </div>
                <span class="btn-label">{{ video.favorite_count || 0 }}</span>
              </button>

              <!-- 稍后看 -->
              <button
                class="interact-btn watchlater-btn"
                :class="{ active: isWatchLater }"
                @click="handleWatchLater"
                data-testid="watchlater-button"
              >
                <div class="btn-icon">
                  <svg v-if="!isWatchLater" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14"/>
                  </svg>
                  <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <circle cx="12" cy="12" r="10"/>
                    <polyline points="12 6 12 12 16 14" stroke="currentColor" fill="none" stroke-width="2"/>
                  </svg>
                </div>
                <span class="btn-label">稍后看</span>
              </button>

              <!-- 共享观看 -->
              <button
                class="interact-btn sharewatch-btn"
                :class="{ active: isSharedMode }"
                @click="isSharedMode ? showShareDialog = true : createSharedWatchSession()"
                data-testid="sharewatch-button"
              >
                <div class="btn-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                    <circle cx="9" cy="7" r="4"/>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                  </svg>
                </div>
                <span class="btn-label">{{ isSharedMode ? '共享中' : '共享' }}</span>
              </button>

              <!-- 下载 -->
              <button class="action-btn" @click="handleDownload" data-testid="download-button">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                <span class="btn-label">下载</span>
              </button>

              <!-- 分享 -->
              <button class="action-btn" @click="handleShare" data-testid="share-button">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="18" cy="5" r="3"/>
                  <circle cx="6" cy="12" r="3"/>
                  <circle cx="18" cy="19" r="3"/>
                  <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
                  <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
                </svg>
                <span class="btn-label">分享</span>
              </button>
            </div>

            <!-- 第二行：管理按钮 - 仅管理员可见 -->
            <div v-if="isAdmin" class="action-buttons">
              <button class="action-btn edit-btn" @click="startEdit" data-testid="edit-button" title="编辑">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
              </button>

              <button class="action-btn delete-btn" @click="confirmDelete" data-testid="delete-button" title="删除">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  <line x1="10" y1="11" x2="10" y2="17"/>
                  <line x1="14" y1="11" x2="14" y2="17"/>
                </svg>
              </button>
            </div>
          </div>
        </template>
      </div>

      <!-- 删除确认对话框 -->
      <div v-if="showDeleteConfirm" class="dialog-overlay" data-testid="delete-confirm-dialog">
        <div class="dialog">
          <h3>确认删除</h3>
          <p>确定要删除视频 "{{ video.title }}" 吗？</p>
          <div class="dialog-checkbox">
            <label>
              <input type="checkbox" v-model="deleteFileOption" />
              同时删除视频文件（不可恢复）
            </label>
          </div>
          <div class="dialog-actions">
            <button class="btn-secondary" @click="showDeleteConfirm = false">取消</button>
            <button class="btn-danger" @click="handleDelete" data-testid="confirm-delete-button">删除</button>
          </div>
        </div>
      </div>

      <!-- 共享观看对话框 -->
      <div v-if="showShareDialog" class="dialog-overlay" data-testid="share-watch-dialog">
        <div class="dialog share-dialog">
          <h3>共享观看</h3>
          <div class="share-info">
            <p class="share-label">分享链接：</p>
            <div class="share-url-box">
              <input 
                type="text" 
                :value="shareUrl" 
                readonly 
                class="share-url-input"
                data-testid="share-url-input"
              />
              <button 
                class="btn-copy" 
                @click="copyShareUrl"
                data-testid="copy-share-url-button"
              >
                复制
              </button>
            </div>
            <p class="share-hint">将此链接分享给好友，即可一起观看视频，播放进度将自动同步</p>
            <div v-if="sharedSession" class="share-status">
              <p class="status-item">
                <span class="status-label">状态：</span>
                <span :class="['status-value', sharedSession.status]">
                  {{ sharedSession.status === 'pending' ? '等待加入' : '观看中' }}
                </span>
              </p>
              <p class="status-item" v-if="sharedSession.invitee_id">
                <span class="status-label">已加入用户</span>
              </p>
            </div>
          </div>
          <div class="dialog-actions">
            <button 
              v-if="isCreator" 
              class="btn-danger" 
              @click="endSharedWatchSession(); showShareDialog = false"
              data-testid="end-share-button"
            >
              结束共享
            </button>
            <button class="btn-secondary" @click="showShareDialog = false">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 视频不存在 -->
    <div v-else class="error-container">
      <p>视频不存在或已被删除</p>
      <button @click="goBack" class="back-link">返回首页</button>
    </div>

    <!-- Toast 提示 -->
    <div v-if="showToastFlag" class="toast" data-testid="favorite-success">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.video-page {
  min-height: 100vh;
  background: #0f0f0f;
  color: #fff;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 24px;
  background: transparent;
  border: none;
  color: #fff;
  font-size: 16px;
  cursor: pointer;
  transition: color 0.2s;
}

.back-btn:hover {
  color: #2196F3;
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 3px solid #333;
  border-top-color: #2196F3;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.video-content {
  max-width: 1400px;
  margin: 0 auto;
  padding: 0 24px 40px;
}

.player-section {
  background: #000;
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 24px;
}

.video-player-container {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
}

.video-element {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.player-controls {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  background: #1a1a1a;
}

.control-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  background: transparent;
  border: none;
  color: #fff;
  cursor: pointer;
  border-radius: 50%;
  transition: background 0.2s;
}

.control-btn:hover {
  background: rgba(255, 255, 255, 0.1);
}

.progress-bar {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.time {
  font-size: 13px;
  color: #999;
  min-width: 45px;
  text-align: center;
}

.seek-slider {
  flex: 1;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: #444;
  border-radius: 2px;
  cursor: pointer;
}

.seek-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 12px;
  height: 12px;
  background: #2196F3;
  border-radius: 50%;
  cursor: pointer;
}

.volume-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.volume-slider {
  width: 80px;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: #444;
  border-radius: 2px;
  cursor: pointer;
}

.volume-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 10px;
  height: 10px;
  background: #fff;
  border-radius: 50%;
  cursor: pointer;
}

.video-info-section {
  background: #1a1a1a;
  border-radius: 12px;
  padding: 24px;
}

.video-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0;
  color: #fff;
}

.video-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.video-meta {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  color: #999;
  font-size: 14px;
}

.video-description {
  font-size: 15px;
  line-height: 1.6;
  color: #ccc;
  margin-bottom: 16px;
  white-space: pre-wrap;
}

.video-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}

.tag-badge {
  padding: 6px 12px;
  background: #333;
  border-radius: 16px;
  font-size: 13px;
  color: #ccc;
}

/* 交互按钮栏 */
.interaction-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  padding: 20px 0;
  border-top: 1px solid #333;
  border-bottom: 1px solid #333;
  margin: 20px 0;
}

/* 左侧交互按钮组 */
.interaction-buttons {
  display: flex;
  gap: 8px;
}

.interact-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #888;
  cursor: pointer;
  transition: all 0.2s ease;
}

.interact-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #aaa;
  transform: scale(1.05);
}

.interact-btn .btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: transparent;
  transition: all 0.2s ease;
}

.interact-btn:hover .btn-icon {
  background: rgba(255, 255, 255, 0.1);
}

.interact-btn .btn-label {
  display: block;
  font-size: 11px;
  color: #888;
  line-height: 1.2;
}

/* 点赞按钮 */
.interact-btn.like-btn:hover,
.interact-btn.like-btn.active {
  color: #ff6b6b;
}

.interact-btn.like-btn:hover .btn-icon,
.interact-btn.like-btn.active .btn-icon {
  background: rgba(255, 107, 107, 0.15);
}

.interact-btn.like-btn.active .btn-icon {
  animation: likeAnim 0.3s ease;
}

@keyframes likeAnim {
  0% { transform: scale(1); }
  50% { transform: scale(1.3); }
  100% { transform: scale(1); }
}

/* 踩按钮 */
.interact-btn.dislike-btn:hover,
.interact-btn.dislike-btn.active {
  color: #ffd93d;
}

.interact-btn.dislike-btn:hover .btn-icon,
.interact-btn.dislike-btn.active .btn-icon {
  background: rgba(255, 217, 61, 0.15);
}

/* 收藏按钮 */
.interact-btn.favorite-btn:hover,
.interact-btn.favorite-btn.active {
  color: #ff6b9d;
}

.interact-btn.favorite-btn:hover .btn-icon,
.interact-btn.favorite-btn.active .btn-icon {
  background: rgba(255, 107, 157, 0.15);
}

.interact-btn.favorite-btn.active .btn-icon {
  animation: favoriteAnim 0.4s ease;
}

@keyframes favoriteAnim {
  0% { transform: scale(1); }
  25% { transform: scale(1.2); }
  50% { transform: scale(0.95); }
  75% { transform: scale(1.1); }
  100% { transform: scale(1); }
}

/* 稍后看按钮 */
.interact-btn.watchlater-btn:hover,
.interact-btn.watchlater-btn.active {
  color: #69dbff;
}

.interact-btn.watchlater-btn:hover .btn-icon,
.interact-btn.watchlater-btn.active .btn-icon {
  background: rgba(105, 219, 255, 0.15);
}

.interact-btn.watchlater-btn.active .btn-icon svg polyline {
  stroke: #69dbff;
}

/* 共享观看按钮 */
.interact-btn.sharewatch-btn:hover,
.interact-btn.sharewatch-btn.active {
  color: #2196F3;
}

.interact-btn.sharewatch-btn:hover .btn-icon,
.interact-btn.sharewatch-btn.active .btn-icon {
  background: rgba(33, 150, 243, 0.15);
}

/* 右侧操作按钮 */
.action-buttons {
  display: flex;
  gap: 4px;
}

.action-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: #888;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #aaa;
  transform: scale(1.05);
}

.action-btn.active {
  color: #2196F3;
}

.action-btn.active:hover {
  color: #fff;
}

.action-btn .btn-label {
  display: block;
  font-size: 11px;
  color: #888;
  line-height: 1.2;
}

.error-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  color: #999;
}

.back-link {
  margin-top: 16px;
  padding: 10px 24px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}

/* 编辑表单 */
.edit-form {
  background: #252525;
  border-radius: 12px;
  padding: 24px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-size: 14px;
  color: #999;
  margin-bottom: 8px;
}

/* 标签输入框包装器 */
.tag-input-wrapper {
  position: relative;
}

.tag-input-wrapper input {
  width: 100%;
  padding: 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #252525;
  color: #fff;
  font-size: 14px;
  box-sizing: border-box;
}

.tag-input-wrapper input:focus {
  outline: none;
  border-color: #2196F3;
}

/* 标签智能建议下拉框 */
.tag-suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #2a2a2a;
  border: 1px solid #444;
  border-top: none;
  border-radius: 0 0 8px 8px;
  max-height: 200px;
  overflow-y: auto;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.tag-suggestion-item {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #333;
  transition: background 0.2s;
}

.tag-suggestion-item:last-child {
  border-bottom: none;
}

.tag-suggestion-item:hover {
  background: #3a3a3a;
}

.suggestion-path {
  color: #fff;
  font-size: 14px;
}

.form-group input,
.form-group textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid #444;
  border-radius: 8px;
  background: #1a1a1a;
  color: #fff;
  font-size: 15px;
  box-sizing: border-box;
}

.form-group input:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #2196F3;
}

.form-group textarea {
  resize: vertical;
  min-height: 100px;
}

.form-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.btn-secondary {
  padding: 10px 24px;
  background: transparent;
  border: 1px solid #444;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-secondary:hover {
  background: #333;
}

.btn-primary {
  padding: 10px 24px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: #1976D2;
}

.btn-danger {
  padding: 10px 24px;
  background: #f44336;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-danger:hover {
  background: #d32f2f;
}

.edit-btn:hover {
  background: #2196F3;
}

.delete-btn:hover {
  background: #f44336;
}

/* 对话框 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: #1a1a1a;
  border-radius: 12px;
  padding: 24px;
  width: 90%;
  max-width: 400px;
}

.dialog h3 {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  margin: 0 0 16px 0;
}

.dialog p {
  color: #ccc;
  margin: 0 0 12px 0;
}

.warning-text {
  color: #ff9800;
  font-size: 13px;
}

.dialog-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 20px;
}

.dialog-checkbox {
  margin: 16px 0;
  padding: 12px;
  background: #2a2a2a;
  border-radius: 8px;
}

.dialog-checkbox label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #ccc;
  font-size: 14px;
}

.dialog-checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

/* 共享观看对话框 */
.share-dialog {
  max-width: 500px;
}

.share-info {
  margin-bottom: 20px;
}

.share-label {
  font-size: 14px;
  color: #999;
  margin-bottom: 8px;
}

.share-url-box {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.share-url-input {
  flex: 1;
  padding: 10px 12px;
  background: #252525;
  border: 1px solid #444;
  border-radius: 8px;
  color: #fff;
  font-size: 13px;
  font-family: monospace;
}

.btn-copy {
  padding: 10px 16px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.2s;
}

.btn-copy:hover {
  background: #1976D2;
}

.share-hint {
  font-size: 13px;
  color: #999;
  line-height: 1.6;
}

.share-status {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #333;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 14px;
}

.status-label {
  color: #999;
}

.status-value {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 13px;
}

.status-value.pending {
  background: #ff9800;
  color: #fff;
}

.status-value.active {
  background: #4caf50;
  color: #fff;
}

/* Toast 提示 */
.toast {
  position: fixed;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.8);
  color: #fff;
  padding: 12px 24px;
  border-radius: 24px;
  font-size: 14px;
  z-index: 2000;
  animation: fadeInOut 2s ease;
}

@keyframes fadeInOut {
  0% { opacity: 0; transform: translateX(-50%) translateY(20px); }
  10% { opacity: 1; transform: translateX(-50%) translateY(0); }
  90% { opacity: 1; transform: translateX(-50%) translateY(0); }
  100% { opacity: 0; transform: translateX(-50%) translateY(-20px); }
}

@media (max-width: 768px) {
  .video-content {
    padding: 0 16px 32px;
  }

  .video-title {
    font-size: 18px;
  }

  /* 交互按钮移动端适配 - 允许换行 */
  .interaction-bar {
    gap: 12px;
    padding: 16px 0;
  }

  .interaction-buttons {
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
  }

  .interact-btn {
    padding: 6px 4px;
    flex: 1 1 calc(33% - 4px);
    max-width: calc(33% - 4px);
    min-width: 60px;
  }

  .interact-btn .btn-icon {
    width: 24px;
    height: 24px;
  }

  .interact-btn svg {
    width: 18px;
    height: 18px;
  }

  .interact-btn .btn-label {
    font-size: 10px;
  }

  .action-buttons {
    gap: 4px;
    justify-content: center;
  }

  .action-btn {
    padding: 6px 8px;
    flex: 1 1 calc(50% - 4px);
    max-width: calc(50% - 4px);
  }

  .action-btn svg {
    width: 18px;
    height: 18px;
  }

  .action-btn .btn-label {
    font-size: 10px;
  }

  .player-controls {
    gap: 8px;
    padding: 8px 12px;
  }

  .volume-control {
    display: none;
  }
}
</style>
