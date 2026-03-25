<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import VideoCard from '../components/VideoCard.vue'
import TagBadge from '../components/TagBadge.vue'
import type { Video, Tag } from '../types'

const router = useRouter()
const videoStore = useVideoStore()

const loading = computed(() => videoStore.loading)
const videos = computed(() => videoStore.videos)
const tags = computed(() => videoStore.tags)
const selectedTagId = computed(() => videoStore.selectedTagId)
const searchQuery = computed({
  get: () => videoStore.searchQuery,
  set: (val) => videoStore.searchQuery = val
})

// 排序选项
const sortOptions = [
  { value: 'recommended', label: '推荐' },
  { value: 'name', label: '视频名' },
  { value: 'created_at', label: '文件时间' },
  { value: 'view_count', label: '播放量' },
  { value: 'priority', label: '优先级' },
  { value: 'like_count', label: '点赞数' },
  { value: 'download_count', label: '下载数' }
]

const currentSort = computed(() => videoStore.sortBy)
const currentOrder = computed(() => videoStore.sortOrder)

const handleSortChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  videoStore.setSortBy(target.value)
}

const handleOrderChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  videoStore.setSortOrder(target.value)
}

onMounted(async () => {
  await Promise.all([
    videoStore.fetchVideos(true),
    videoStore.fetchTags()
  ])
})

// 搜索防抖
let searchTimeout: number | null = null
watch(() => videoStore.searchQuery, (newQuery) => {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = window.setTimeout(() => {
    videoStore.searchVideos(newQuery)
  }, 500)
})

// 清除搜索
const clearSearch = () => {
  videoStore.clearSearch()
}

const handleTagClick = async (tag: Tag) => {
  if (selectedTagId.value === tag.id) {
    await videoStore.filterByTag(null)
  } else {
    await videoStore.filterByTag(tag.id)
  }
}

const handleVideoClick = (video: Video) => {
  router.push({ name: 'Video', params: { hash: video.hash } })
}

const loadMore = async () => {
  await videoStore.loadMore()
}

const shuffling = ref(false)

const handleShuffle = async () => {
  shuffling.value = true
  await videoStore.shuffleVideos()
  shuffling.value = false
}

const handleUndo = async () => {
  shuffling.value = true
  await videoStore.undoShuffle()
  shuffling.value = false
}

const hasPreviousVideos = computed(() => videoStore.previousVideos && videoStore.previousVideos.length > 0)

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
</script>

<template>
  <div class="home-container">
    <!-- 标签区域 - 移到最顶部 -->
    <div class="tags-section">
      <div class="tags-header">
        <h3>标签筛选</h3>
      </div>
      <div class="tags-container">
        <TagBadge
          :tag="{ id: 0, name: '全部', video_count: 0 }"
          :active="selectedTagId === null"
          @click="() => videoStore.filterByTag(null)"
        />
        <TagBadge
          v-for="tag in tags"
          :key="tag.id"
          :tag="tag"
          :active="selectedTagId === tag.id"
          @click="handleTagClick(tag)"
        />
      </div>
    </div>

    <!-- 操作栏 - 移到顶部 -->
    <div class="action-bar">
      <div class="search-box">
        <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索视频标题..."
          class="search-input"
        />
        <button v-if="searchQuery" class="clear-search-btn" @click="clearSearch">×</button>
      </div>
      <div class="sort-box">
        <label class="sort-label">排序：</label>
        <select class="sort-select" :value="currentSort" @change="handleSortChange">
          <option v-for="option in sortOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
        <select class="sort-order-select" :value="currentOrder" @change="handleOrderChange">
          <option value="desc">倒序</option>
          <option value="asc">正序</option>
        </select>
        <!-- 换一批按钮 -->
        <button class="shuffle-btn" @click="handleShuffle" :disabled="shuffling" title="换一批">
          <svg class="shuffle-icon" :class="{ spinning: shuffling }" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l4.4-6c.6-.9 1.9-1.4 3-1.1l5.8 1.6"/>
            <path d="M22 6h-1.4c-1.3 0-2.5.6-3.3 1.7l-4.4 6c-.6.9-1.9 1.4-3 1.1l-5.8-1.6"/>
            <path d="M7.5 12L5 8l9 4-2.5 4"/>
            <path d="M16.5 12L19 16l-9-4 2.5-4"/>
          </svg>
          <span class="shuffle-text">{{ shuffling ? '换选中...' : '换一批' }}</span>
        </button>
        <!-- 撤回按钮 -->
        <button v-if="hasPreviousVideos" class="undo-btn" @click="handleUndo" :disabled="shuffling" title="撤回">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 10h10c4.4 0 8 3.6 8 8v2"/>
            <path d="M7 6L3 10l4 4"/>
          </svg>
          <span class="undo-text">撤回</span>
        </button>
      </div>
      <div v-if="searchQuery" class="search-status">
        搜索: "{{ searchQuery }}" ({{ videos.length }} 个结果)
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 视频网格 - 所有视频统一显示 -->
    <template v-else>
      <div v-if="videos.length > 0" class="video-section">
        <div class="video-grid">
          <VideoCard
            v-for="video in videos"
            :key="video.hash"
            :video="video"
            @click="handleVideoClick(video)"
          />
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="videos.length === 0" class="empty-state">
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1">
          <rect x="2" y="4" width="20" height="16" rx="2"/>
          <path d="M10 9l5 3-5 3V9z"/>
        </svg>
        <p>暂无视频</p>
      </div>

      <!-- 加载更多 -->
      <div v-if="videos.length > 0 && videoStore.hasMore" class="load-more">
        <button @click="loadMore" class="load-more-btn">加载更多</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.home-container {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* 标签区域 */
.tags-section {
  margin-bottom: 24px;
  background: #1a1a1a;
  border-radius: 12px;
  padding: 16px;
}

.tags-header {
  margin-bottom: 12px;
}

.tags-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  margin: 0;
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 操作栏 */
.action-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  align-items: center;
  flex-wrap: wrap;
}

/* 排序选择器 */
.sort-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sort-label {
  color: #aaa;
  font-size: 14px;
}

.sort-select {
  height: 40px;
  padding: 0 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #1a1a1a;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.sort-select:hover {
  border-color: #4a9eff;
}

.sort-select:focus {
  outline: none;
  border-color: #4a9eff;
  box-shadow: 0 0 0 2px rgba(74, 158, 255, 0.2);
}

.sort-order-select {
  height: 40px;
  padding: 0 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #1a1a1a;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.2s;
  margin-left: 8px;
}

.sort-order-select:hover {
  border-color: #4a9eff;
}

.sort-order-select:focus {
  outline: none;
  border-color: #4a9eff;
  box-shadow: 0 0 0 2px rgba(74, 158, 255, 0.2);
}

/* 换一批按钮 */
.shuffle-btn {
  height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(74, 158, 255, 0.3);
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(74, 158, 255, 0.15) 0%, rgba(74, 158, 255, 0.05) 100%);
  color: #4a9eff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.shuffle-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(74, 158, 255, 0.25) 0%, rgba(74, 158, 255, 0.15) 100%);
  border-color: #4a9eff;
  box-shadow: 0 0 20px rgba(74, 158, 255, 0.2);
  transform: translateY(-1px);
}

.shuffle-btn:active:not(:disabled) {
  transform: scale(0.96) translateY(0);
}

.shuffle-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.shuffle-icon {
  flex-shrink: 0;
  transition: transform 0.3s ease;
}

.shuffle-icon.spinning {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.shuffle-text {
  letter-spacing: 0.3px;
}

/* 撤回按钮 */
.undo-btn {
  height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(250, 173, 20, 0.3);
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(250, 173, 20, 0.15) 0%, rgba(250, 173, 20, 0.05) 100%);
  color: #faad14;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.undo-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(250, 173, 20, 0.25) 0%, rgba(250, 173, 20, 0.15) 100%);
  border-color: #faad14;
  box-shadow: 0 0 20px rgba(250, 173, 20, 0.2);
  transform: translateY(-1px);
}

.undo-btn:active:not(:disabled) {
  transform: scale(0.96) translateY(0);
}

.undo-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.undo-text {
  letter-spacing: 0.3px;
}

.search-box {
  flex: 1;
  max-width: 500px;
  position: relative;
}

.search-icon {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  color: #666;
}

.search-input {
  width: 100%;
  height: 48px;
  padding: 0 16px 0 48px;
  border: 1px solid #333;
  border-radius: 12px;
  background: #1a1a1a;
  color: #fff;
  font-size: 15px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.search-input:focus {
  outline: none;
  border-color: #2196F3;
  box-shadow: 0 0 0 3px rgba(33, 150, 243, 0.1);
}

.search-input::placeholder {
  color: #666;
}

.clear-search-btn {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: #333;
  border: none;
  border-radius: 50%;
  width: 20px;
  height: 20px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.clear-search-btn:hover {
  background: #444;
}

.search-status {
  padding: 8px 16px;
  background: #1a1a1a;
  border-radius: 8px;
  color: #888;
  font-size: 14px;
}

/* 加载中 */
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
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

/* 视频网格 */
.video-section {
  margin-bottom: 32px;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  color: #666;
}

.empty-state p {
  margin-top: 16px;
  font-size: 16px;
}

/* 加载更多 */
.load-more {
  display: flex;
  justify-content: center;
  margin-top: 32px;
}

.load-more-btn {
  padding: 14px 48px;
  background: transparent;
  color: #2196F3;
  border: 2px solid #2196F3;
  border-radius: 12px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 500;
  transition: all 0.2s;
}

.load-more-btn:hover {
  background: #2196F3;
  color: #fff;
}

/* 响应式 */
@media (max-width: 1200px) {
  .video-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .video-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .home-container {
    padding: 12px;
    max-width: 100vw;
  }
  
  /* 移动端两列布局 */
  .video-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    width: 100%;
  }
  
  .section-title {
    font-size: 18px;
  }
  
  .tags-section {
    padding: 12px;
    max-width: 100%;
  }
  
  .tags-container {
    max-width: 100%;
  }
  
  .action-bar {
    max-width: 100%;
  }
  
  .search-box {
    max-width: 100%;
  }
  
  .search-input {
    height: 44px;
    font-size: 14px;
  }

  /* 移动端换一批按钮 */
  .shuffle-btn {
    height: 32px;
    padding: 0 10px;
    font-size: 12px;
    gap: 4px;
  }

  .shuffle-btn svg {
    width: 14px;
    height: 14px;
  }

  .undo-btn {
    height: 32px;
    padding: 0 10px;
    font-size: 12px;
    gap: 4px;
  }

  .undo-btn svg {
    width: 14px;
    height: 14px;
  }
}
</style>
