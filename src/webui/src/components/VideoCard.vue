<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Video } from '../types'
import { useUserStore } from '../stores/userStore'
import { useVideoStore } from '../stores/videoStore'

const props = defineProps<{
  video: Video
  size?: 'large' | 'normal' | 'small'
}>()

const emit = defineEmits<{
  click: [video: Video]
}>()

const userStore = useUserStore()
const videoStore = useVideoStore()

// 标记/取消不喜欢（踩）
const handleDislike = (event: Event) => {
  event.stopPropagation()
  videoStore.dislikeVideo(props.video.hash)
}

// 点赞/取消点赞（比较喜欢）
const handleLike = async (event: Event) => {
  event.stopPropagation()
  await videoStore.likeVideo(props.video.hash)
}

// 收藏/取消收藏（非常喜欢）
const handleFavorite = async (event: Event) => {
  event.stopPropagation()
  await videoStore.favoriteVideo(props.video.hash)
}

// 监听 video.hash 变化，重置缩略图状态
watch(() => props.video.hash, () => {
  loadThumbnail()
})

// 缩略图URL和加载状态
const thumbnailUrl = ref('')
const isLoading = ref(true)
const hasError = ref(false)

const loadThumbnail = () => {
  if (!props.video.thumbnail) {
    thumbnailUrl.value = '/placeholder.jpg'
    isLoading.value = false
    return
  }

  const token = userStore.token
  const baseUrl = props.video.thumbnail
  thumbnailUrl.value = token ? `${baseUrl}?token=${token}` : baseUrl
  isLoading.value = false
}

// 组件挂载时加载缩略图
loadThumbnail()

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

const handleImageLoad = () => {
  isLoading.value = false
  hasError.value = false
}

const handleImageError = () => {
  // 加载失败显示默认图
  isLoading.value = false
  hasError.value = true
  thumbnailUrl.value = '/placeholder.jpg'
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
        :class="{ 'thumbnail-error': hasError }"
        data-testid="video-thumbnail"
        @error="handleImageError"
        @load="handleImageLoad"
      />
      <!-- 时长标签 -->
      <span class="duration" v-if="video.duration" data-testid="video-duration">
        {{ formatDuration(video.duration) }}
      </span>
      <!-- 卡片右上角操作：点赞(左) 收藏(中) 我不喜欢(右) -->
      <div class="card-actions">
        <!-- 点赞：比较喜欢 -->
        <button
          class="card-action-btn like-action"
          :class="{ active: video.is_liked }"
          @click="handleLike"
          :title="video.is_liked ? '取消点赞' : '点赞'"
          data-testid="card-like-button"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" :fill="video.is_liked ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
        </button>
        <!-- 收藏：非常喜欢 -->
        <button
          class="card-action-btn favorite-action"
          :class="{ active: video.is_favorited }"
          @click="handleFavorite"
          :title="video.is_favorited ? '取消收藏' : '收藏'"
          data-testid="card-favorite-button"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" :fill="video.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
        </button>
        <!-- 不喜欢按钮 -->
        <button
          class="card-action-btn dislike-action"
          :class="{ active: video.disliked }"
          @click="handleDislike"
          :title="video.disliked ? '取消屏蔽' : '我不喜欢'"
          data-testid="card-dislike-button"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
          </svg>
        </button>
      </div>
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
        <!-- 点赞状态：是否已点赞 -->
        <span class="liked-flag" v-if="video.is_liked" data-testid="liked-flag">
          <svg width="14" height="14" viewBox="0 0 24 24" :fill="'currentColor'" stroke="currentColor" stroke-width="2">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
          已赞
        </span>
        <!-- 点赞数 -->
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

.thumbnail-error {
  opacity: 0.5;
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

/* 卡片右上角操作区：点赞(左) 收藏(中) 我不喜欢(右)，默认隐藏，hover 显示，已激活时始终显示 */
.card-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 6px;
  z-index: 2;
}

.card-action-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  border: none;
  border-radius: 50%;
  color: #fff;
  cursor: pointer;
  opacity: 1;
  transition: background 0.2s ease, color 0.2s ease;
}

.card-action-btn:hover {
  background: rgba(0, 0, 0, 0.8);
}

/* 点赞：比较喜欢（红色） */
.like-action:hover,
.like-action.active {
  color: #ff4757;
}
.like-action.active {
  background: rgba(255, 71, 87, 0.2);
}

/* 收藏：非常喜欢（金色） */
.favorite-action:hover,
.favorite-action.active {
  color: #ffa502;
}
.favorite-action.active {
  background: rgba(255, 165, 2, 0.2);
}

/* 我不喜欢（黄色） */
.dislike-action:hover {
  color: #ffd93d;
}
.dislike-action.active {
  color: #ffd93d;
  background: rgba(255, 217, 61, 0.2);
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

/* 已赞状态标记 */
.liked-flag {
  display: flex;
  align-items: center;
  gap: 3px;
  color: #ff4757;
  font-weight: 500;
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