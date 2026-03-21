<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import type { Video } from '../types'

const route = useRoute()
const router = useRouter()
const videoStore = useVideoStore()

const video = ref<Video | null>(null)
const loading = ref(true)
const isFavorited = ref(false)
const isLiked = ref(false)
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

// 视频源URL - 直接使用后端返回的url字段，已包含正确格式
const videoUrl = computed(() => {
  return video.value?.url || ''
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
  const favoritedVideos = JSON.parse(localStorage.getItem('favoritedVideos') || '[]')
  isLiked.value = likedVideos.includes(video.value.hash)
  isFavorited.value = favoritedVideos.includes(video.value.hash)
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
    await fetch(`/api/video/${videoHash.value}/view`, { method: 'POST' })
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
    await fetch(`/api/video/${video.value.hash}/download`, { method: 'POST' })
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

const startEdit = () => {
  if (!video.value) return
  editTitle.value = video.value.title
  editDescription.value = video.value.description || ''
  editPriority.value = video.value.priority || 0
  editTags.value = video.value.tags?.map(t => t.name).join(', ') || ''
  isEditing.value = true
}

const cancelEdit = () => {
  isEditing.value = false
}

const saveEdit = async () => {
  if (!video.value) return
  
  try {
    await videoStore.updateVideo(video.value.hash, {
      title: editTitle.value,
      description: editDescription.value,
      priority: editPriority.value,
      tags: editTags.value
    })
    
    // 更新本地视频数据
    video.value.title = editTitle.value
    video.value.description = editDescription.value
    video.value.priority = editPriority.value
    
    isEditing.value = false
  } catch (e) {
    alert('保存失败')
  }
}

// 删除视频
const showDeleteConfirm = ref(false)

const confirmDelete = () => {
  showDeleteConfirm.value = true
}

const handleDelete = async () => {
  if (!video.value) return
  
  try {
    await videoStore.deleteVideo(video.value.hash)
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
            <label>标签 (用逗号分隔)</label>
            <input 
              v-model="editTags" 
              type="text" 
              data-testid="tag-selector"
              placeholder="例如: 动作,科幻,热门"
            />
          </div>
          <div class="form-actions">
            <button class="btn-secondary" @click="cancelEdit" data-testid="cancel-button">取消</button>
            <button class="btn-primary" @click="saveEdit" data-testid="save-button">保存</button>
          </div>
        </div>

        <!-- 查看模式 -->
        <template v-else>
          <h1 class="video-title" data-testid="video-title">{{ video.title }}</h1>
          
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

          <!-- 操作按钮 -->
          <div class="action-buttons">
            <button 
              class="action-btn" 
              :class="{ active: isLiked }"
              @click="handleLike"
              data-testid="like-button"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M1 21h4V9H1v12zm22-11c0-1.1-.9-2-2-2h-6.31l.95-4.57.03-.32c0-.41-.17-.79-.44-1.06L14.17 1 7.59 7.59C7.22 7.95 7 8.45 7 9v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-2z"/>
              </svg>
              点赞 ({{ video.like_count }})
            </button>

            <button 
              class="action-btn" 
              :class="{ active: isFavorited }"
              @click="handleFavorite"
              data-testid="favorite-button"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
              </svg>
              收藏
            </button>

            <button class="action-btn" @click="handleDownload" data-testid="download-button">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/>
              </svg>
              下载
            </button>

            <button class="action-btn" @click="handleShare" data-testid="share-button">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M18 16.08c-.76 0-1.44.3-1.96.77L8.91 12.7c.05-.23.09-.46.09-.7s-.04-.47-.09-.7l7.05-4.11c.54.5 1.25.81 2.04.81 1.66 0 3-1.34 3-3s-1.34-3-3-3-3 1.34-3 3c0 .24.04.47.09.7L8.04 9.81C7.5 9.31 6.79 9 6 9c-1.66 0-3 1.34-3 3s1.34 3 3 3c.79 0 1.5-.31 2.04-.81l7.12 4.16c-.05.21-.08.43-.08.65 0 1.61 1.31 2.92 2.92 2.92 1.61 0 2.92-1.31 2.92-2.92s-1.31-2.92-2.92-2.92z"/>
              </svg>
              分享
            </button>

            <button 
              class="action-btn share-watch-btn" 
              :class="{ active: isSharedMode }"
              @click="isSharedMode ? showShareDialog = true : createSharedWatchSession()"
              data-testid="share-watch-button"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M16 11c1.66 0 2.99-1.34 2.99-3S17.66 5 16 5c-1.66 0-3 1.34-3 3s1.34 3 3 3zm-8 0c1.66 0 2.99-1.34 2.99-3S9.66 5 8 5C6.34 5 5 6.34 5 8s1.34 3 3 3zm0 2c-2.33 0-7 1.17-7 3.5V19h14v-2.5c0-2.33-4.67-3.5-7-3.5zm8 0c-.29 0-.62.02-.97.05 1.16.84 1.97 1.97 1.97 3.45V19h6v-2.5c0-2.33-4.67-3.5-7-3.5z"/>
              </svg>
              {{ isSharedMode ? '共享中' : '共享观看' }}
            </button>

            <button class="action-btn edit-btn" @click="startEdit" data-testid="edit-button">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
              </svg>
              编辑
            </button>

            <button class="action-btn delete-btn" @click="confirmDelete" data-testid="delete-button">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
              </svg>
              删除
            </button>
          </div>
        </template>
      </div>

      <!-- 删除确认对话框 -->
      <div v-if="showDeleteConfirm" class="dialog-overlay" data-testid="delete-confirm-dialog">
        <div class="dialog">
          <h3>确认删除</h3>
          <p>确定要删除视频 "{{ video.title }}" 吗？</p>
          <p class="warning-text">此操作不可恢复。</p>
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
  margin: 0 0 12px 0;
  color: #fff;
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

.action-buttons {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.action-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 20px;
  background: #333;
  border: none;
  border-radius: 20px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:hover {
  background: #444;
}

.action-btn.active {
  background: #2196F3;
}

.action-btn.active:hover {
  background: #1976D2;
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

.share-watch-btn {
  background: #9c27b0;
}

.share-watch-btn:hover {
  background: #7b1fa2;
}

.share-watch-btn.active {
  background: #4caf50;
}

.share-watch-btn.active:hover {
  background: #388e3c;
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

  .action-buttons {
    gap: 8px;
  }

  .action-btn {
    padding: 8px 16px;
    font-size: 13px;
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
