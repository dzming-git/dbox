<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import type { Video } from '../types'
import { useUserStore } from '../stores/userStore'

const props = defineProps<{
  video: Video
  size?: 'large' | 'normal' | 'small'
}>()

const emit = defineEmits<{
  click: [video: Video]
}>()

const userStore = useUserStore()

// 缩略图URL和加载状态
const thumbnailUrl = ref('')
const isLoading = ref(true)
const hasError = ref(false)
const thumbnailProgress = ref(0)  // 缩略图生成进度
const thumbnailStatus = ref('')   // 状态文本

// 检查缩略图状态并轮询
let pollTimer: number | null = null

const checkThumbnailStatus = async (hash: string) => {
  try {
    const response = await fetch(`/api/thumbnail/status/${hash}`)
    const data = await response.json()

    if (data.success && data.status === 'ready') {
      // 缩略图已生成，重新加载图片
      const token = userStore.token
      if (token) {
        thumbnailUrl.value = `/thumbnail/${hash}?token=${token}&t=${Date.now()}`
      } else {
        thumbnailUrl.value = `/thumbnail/${hash}?t=${Date.now()}`
      }
      isLoading.value = false
      thumbnailProgress.value = 100
      thumbnailStatus.value = ''
      // 停止轮询
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
    } else if (data.status === 'processing' || data.status === 'pending') {
      // 正在生成，更新进度
      thumbnailProgress.value = data.progress || 0
      thumbnailStatus.value = data.message || `生成中 ${data.progress || 0}%`
    } else if (data.status === 'failed') {
      // 生成失败
      hasError.value = true
      isLoading.value = false
      thumbnailStatus.value = '生成失败'
      if (pollTimer) {
        clearInterval(pollTimer)
        pollTimer = null
      }
    }
  } catch (e) {
    console.error('检查缩略图状态失败:', e)
  }
}

const loadThumbnail = async () => {
  if (!props.video.thumbnail) {
    thumbnailUrl.value = '/placeholder.jpg'
    isLoading.value = false
    return
  }

  // 缩略图 URL 格式: /thumbnail/{hash}
  // 添加 token 参数用于认证
  const token = userStore.token
  const baseUrl = props.video.thumbnail
  if (token) {
    // 添加 token 作为查询参数
    thumbnailUrl.value = `${baseUrl}?token=${token}`
  } else {
    thumbnailUrl.value = baseUrl
  }
  // 设置URL后立即允许显示图片，由 @load/@error 事件处理加载结果
  isLoading.value = false
}

// 处理图片加载错误
const handleImageError = () => {
  // 图片加载失败，可能是后端正在生成或权限问题
  // 启动轮询检查状态
  if (!pollTimer) {
    isLoading.value = true
    thumbnailStatus.value = '生成中...'
    pollTimer = window.setInterval(() => {
      checkThumbnailStatus(props.video.hash)
    }, 2000) // 每2秒检查一次

    // 立即检查一次
    checkThumbnailStatus(props.video.hash)
  }
}

// 处理图片加载成功
const handleImageLoad = () => {
  isLoading.value = false
  hasError.value = false
  thumbnailProgress.value = 100
  thumbnailStatus.value = ''
  // 停止轮询
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// 组件挂载时加载缩略图
onMounted(() => {
  loadThumbnail()
})

// 组件卸载时清理定时器
onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
})

// 格式化时长
const formatDuration = (seconds?: number): string => {
  if (!seconds) return '00:00'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  return `${m}:${s.toString().padStart(2, '0')}`
}

// 卡片样式 - 使用响应式高度，宽度由网格控制
const cardStyle = computed(() => {
  const sizeMap = {
    large: { height: '180px' },
    normal: { height: '135px' },
    small: { height: '101px' }
  }
  return sizeMap[props.size || 'normal']
})

const handleClick = () => {
  emit('click', props.video)
}
</script>

<template>
  <div 
    class="video-card" 
    @click="handleClick"
    data-testid="video-card"
    :data-hash="video.hash"
  >
    <!-- 缩略图容器 -->
    <div class="thumbnail-container" :style="{ height: cardStyle.height }">
      <!-- 加载占位符 -->
      <div v-if="isLoading" class="thumbnail-loading">
        <div class="loading-spinner"></div>
      </div>
      <img
        v-show="!isLoading"
        :src="thumbnailUrl"
        :alt="video.title"
        loading="lazy"
        class="thumbnail"
        data-testid="video-thumbnail"
        @error="handleImageError"
        @load="handleImageLoad"
      />
      <!-- 缩略图生成进度（右上角） -->
      <div v-if="isLoading && thumbnailProgress > 0" class="thumbnail-progress">
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: thumbnailProgress + '%' }"></div>
        </div>
        <span class="progress-text">{{ thumbnailProgress }}%</span>
      </div>
      <!-- 生成状态提示 -->
      <div v-if="isLoading && thumbnailStatus && thumbnailProgress === 0" class="thumbnail-status">
        {{ thumbnailStatus }}
      </div>
      <!-- 时长标签 -->
      <span class="duration" v-if="video.duration" data-testid="video-duration">
        {{ formatDuration(video.duration) }}
      </span>
      <!-- 播放图标 -->
      <div class="play-overlay">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="white">
          <path d="M8 5v14l11-7z"/>
        </svg>
      </div>
    </div>
    
    <!-- 视频信息 -->
    <div class="video-info">
      <h3 class="title" :title="video.title" data-testid="video-title">{{ video.title }}</h3>
      <div class="meta">
        <span class="views" data-testid="view-count">{{ video.view_count }} 次播放</span>
        <span class="likes" v-if="video.like_count > 0" data-testid="like-count">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
          {{ video.like_count }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.video-card {
  cursor: pointer;
  transition: transform 0.2s ease;
  width: 100%;
  max-width: 100%;
  min-width: 0;
}

.video-card:hover {
  transform: scale(1.02);
}

.thumbnail-container {
  position: relative;
  overflow: hidden;
  border-radius: 8px;
  background: #1a1a1a;
  width: 100%;
}

.thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  max-width: 100%;
}

.thumbnail-loading {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #1a1a1a;
}

.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid #333;
  border-top-color: #2196F3;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 缩略图生成进度 */
.thumbnail-progress {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  background: rgba(0, 0, 0, 0.75);
  padding: 4px 8px;
  border-radius: 4px;
  z-index: 10;
}

.progress-bar {
  width: 40px;
  height: 4px;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 2px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: #2196F3;
  transition: width 0.3s ease;
}

.progress-text {
  font-size: 11px;
  color: #fff;
  font-weight: 500;
  min-width: 28px;
  text-align: right;
}

.thumbnail-status {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(0, 0, 0, 0.75);
  color: #fff;
  padding: 6px 12px;
  border-radius: 4px;
  font-size: 12px;
  white-space: nowrap;
  z-index: 10;
}

.duration {
  position: absolute;
  bottom: 8px;
  right: 8px;
  background: rgba(0, 0, 0, 0.7);
  color: white;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.play-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  opacity: 0;
  transition: opacity 0.2s ease;
}

.video-card:hover .play-overlay {
  opacity: 0.9;
}

.video-info {
  padding: 8px 0;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}

.title {
  font-size: 14px;
  font-weight: 500;
  color: #fff;
  margin: 0 0 4px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;  /* 最多显示2行 */
  -webkit-box-orient: vertical;
  line-clamp: 2;
  max-width: 100%;
  width: 100%;
  height: 40px;  /* 两行固定高度 */
}

.meta {
  display: flex;
  gap: 12px;
  font-size: 12px;
  color: #999;
  max-width: 100%;
  overflow: hidden;
}

.likes {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #ff6b6b;
}

/* 响应式 */
@media (max-width: 600px) {
  .video-info {
    padding: 6px 0;
  }
  
  .title {
    font-size: 13px;
  }
  
  .meta {
    font-size: 11px;
    gap: 8px;
  }
  
  .duration {
    font-size: 10px;
    padding: 1px 4px;
  }
}
</style>
