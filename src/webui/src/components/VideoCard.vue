<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Video } from '../types'
import { useUserStore } from '../stores/userStore'
import { withThumbToken } from '../utils/media'
import WatchLaterButton from './WatchLaterButton.vue'

const props = defineProps<{
  video: Video
  size?: 'large' | 'normal' | 'small'
  editable?: boolean
}>()

const emit = defineEmits<{
  click: [video: Video]
  edit: [video: Video]
  tagClick: [tag: any]
}>()

const userStore = useUserStore()

// 将视频标签展开为可点击的标签（含选中的补充项，以 名称/补充项 形式展示）
const tagLabels = computed(() => {
  const out: { key: string | number; label: string; tag: any }[] = []
  for (const t of (props.video.tags || [])) {
    const quals = (t.selected_qualifiers as string[]) || []
    if (quals.length) {
      for (const q of quals) {
        out.push({ key: (t.id ?? t.path) + '::' + q, label: `${t.name || t.path}/${q}`, tag: t })
      }
    } else {
      out.push({ key: t.id ?? t.path, label: t.name || t.path, tag: t })
    }
  }
  return out
})

// 监听 video.hash 变化，重置缩略图状态
watch(() => props.video.hash, () => {
  loadThumbnail()
})

// 缩略图URL和加载状态
const thumbnailUrl = ref('')
const isLoading = ref(true)
const hasError = ref(false)
// 缩略图真实宽高比（加载后按原图比例锁定，避免竖屏被裁成 16:9）
const imgAspect = ref<number | null>(null)

const loadThumbnail = () => {
  imgAspect.value = null
  if (!props.video.thumbnail) {
    thumbnailUrl.value = '/placeholder.jpg'
    isLoading.value = false
    return
  }

  const baseUrl = props.video.thumbnail
  thumbnailUrl.value = withThumbToken(baseUrl)
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

const handleClick = () => {
  if (props.editable) {
    emit('edit', props.video)
    return
  }
  emit('click', props.video)
}

const handleImageLoad = (e: Event) => {
  isLoading.value = false
  hasError.value = false
  const img = e.target as HTMLImageElement
  if (img && img.naturalWidth && img.naturalHeight) {
    // 按原图真实宽高比锁定，竖屏视频不再被裁成横屏
    imgAspect.value = img.naturalWidth / img.naturalHeight
  }
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
    <!-- 缩略图容器：加载后用原图真实宽高比锁定 -->
    <div class="thumbnail-container" :style="imgAspect ? { aspectRatio: String(imgAspect) } : undefined">
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
      <!-- 编辑入口 -->
      <button
        v-if="editable"
        class="edit-overlay"
        @click.stop="emit('edit', video)"
        title="编辑"
        data-testid="card-edit"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>
        </svg>
      </button>

      <!-- 稍后再看角标 -->
      <WatchLaterButton
        variant="overlay"
        type="video"
        :id="video.hash"
        :title="video.title"
        :thumbnail="video.thumbnail"
      />
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
      <!-- 标签：正常模式下点击跳转到该标签筛选 -->
      <div v-if="!editable && video.tags && video.tags.length" class="card-tags">
        <span
          v-for="d in tagLabels"
          :key="d.key"
          class="card-tag"
          :title="'筛选: ' + d.label"
          @click.stop="emit('tagClick', d.tag)"
        >{{ d.label }}</span>
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
  background: var(--bg-surface);
  width: 100%;
  aspect-ratio: 16 / 9; /* 加载完成前占位，加载后由 inline style 覆盖为原图比例 */
}

.thumbnail {
  width: 100%;
  height: 100%;
  object-fit: contain; /* 配合容器真实比例：完整显示、不裁切、不变形 */
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
  background: var(--bg-surface);
}

.loading-spinner {
  width: 24px;
  height: 24px;
  border: 2px solid var(--border-default);
  border-top-color: var(--accent);
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
  color: var(--text-on-accent);
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
  color: var(--text-primary);
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
  color: var(--text-tertiary);
  max-width: 100%;
  overflow: hidden;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.card-tag {
  display: inline-block;
  padding: 2px 8px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  color: var(--text-secondary);
  font-size: 11px;
  cursor: pointer;
}
.card-tag:hover {
  background: var(--accent);
  color: var(--text-on-accent);
}
.edit-overlay {
  position: absolute;
  top: 8px;
  left: 8px;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: rgba(33, 150, 243, 0.85);
  border: none;
  color: var(--text-on-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 4;
}
.edit-overlay:hover {
  background: var(--accent);
}
.likes {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--danger);
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