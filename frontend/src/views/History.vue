<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const history = ref<any[]>([])
const loading = ref(false)

onMounted(() => {
  loading.value = true
  // 从localStorage加载观看历史
  const stored = localStorage.getItem('watchHistory')
  if (stored) {
    history.value = JSON.parse(stored)
  }
  loading.value = false
})

// 跳转到视频详情
const goToVideo = (hash: string) => {
  router.push(`/video/${hash}`)
}

// 继续播放
const continueWatching = (video: any, event: Event) => {
  event.stopPropagation()
  router.push({
    path: `/video/${video.hash}`,
    query: { t: Math.floor(video.progress || 0) }
  })
}

// 删除单条历史
const deleteHistory = (hash: string, event: Event) => {
  event.stopPropagation()
  history.value = history.value.filter(h => h.hash !== hash)
  localStorage.setItem('watchHistory', JSON.stringify(history.value))
  showToast('已删除观看记录')
}

// 清空所有历史
const clearAllHistory = () => {
  if (confirm('确定要清空所有观看历史吗？')) {
    history.value = []
    localStorage.setItem('watchHistory', '[]')
    showToast('已清空观看历史')
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

// 格式化日期
const formatDate = (dateStr: string): string => {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - date.getTime()
  
  // 小于1小时
  if (diff < 3600000) {
    const minutes = Math.floor(diff / 60000)
    return minutes < 1 ? '刚刚' : `${minutes}分钟前`
  }
  // 小于24小时
  if (diff < 86400000) {
    return `${Math.floor(diff / 3600000)}小时前`
  }
  // 小于7天
  if (diff < 604800000) {
    return `${Math.floor(diff / 86400000)}天前`
  }
  
  return date.toLocaleDateString('zh-CN')
}

// 计算进度百分比
const getProgressPercent = (progress: number, duration: number): number => {
  if (!duration) return 0
  return Math.min(100, Math.round((progress / duration) * 100))
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
</script>

<template>
  <div class="history-page">
    <div class="page-header">
      <h1 class="page-title">观看历史</h1>
      <button 
        v-if="history.length > 0" 
        class="clear-btn"
        @click="clearAllHistory"
        data-testid="clear-all-button"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
          <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
        </svg>
        清空历史
      </button>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 空状态 -->
    <div v-else-if="history.length === 0" class="empty-state" data-testid="empty-state">
      <svg class="empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <p>暂无观看记录</p>
      <router-link to="/" class="browse-link">去浏览视频</router-link>
    </div>

    <!-- 历史列表 -->
    <div v-else class="history-list">
      <div 
        v-for="video in history" 
        :key="video.hash"
        class="history-item"
        @click="goToVideo(video.hash)"
        data-testid="history-item"
      >
        <div class="thumbnail-wrapper">
          <img 
            :src="video.thumbnail || '/default-thumb.jpg'" 
            :alt="video.title"
            class="thumbnail"
          />
          <span v-if="video.duration" class="duration">{{ formatDuration(video.duration) }}</span>
          <!-- 进度条 -->
          <div v-if="video.progress > 0" class="progress-bar">
            <div 
              class="progress-fill" 
              :style="{ width: getProgressPercent(video.progress, video.duration) + '%' }"
            ></div>
          </div>
        </div>
        <div class="video-info">
          <h3 class="video-title">{{ video.title }}</h3>
          <div class="video-meta">
            <span class="watch-date">{{ formatDate(video.watched_at) }}</span>
            <span v-if="video.progress > 0" class="progress-text" data-testid="history-progress">
              观看到 {{ formatDuration(video.progress) }}
            </span>
          </div>
        </div>
        <div class="actions">
          <button 
            v-if="video.progress > 0"
            class="continue-btn"
            @click="continueWatching(video, $event)"
            data-testid="continue-button"
          >
            继续播放
          </button>
          <button 
            class="delete-btn"
            @click="deleteHistory(video.hash, $event)"
            data-testid="delete-history-button"
            title="删除记录"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
            </svg>
          </button>
        </div>
      </div>
    </div>

    <!-- Toast 提示 -->
    <div v-if="showToastFlag" class="toast" data-testid="delete-success">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.history-page {
  padding: 24px;
  max-width: 1000px;
  margin: 0 auto;
  min-height: 100vh;
  background: #0f0f0f;
  color: #fff;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 28px;
  font-weight: 600;
  margin: 0;
  color: #fff;
}

.clear-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: transparent;
  border: 1px solid #444;
  border-radius: 8px;
  color: #999;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.clear-btn:hover {
  background: rgba(244, 67, 54, 0.1);
  border-color: #f44336;
  color: #f44336;
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

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  color: #666;
}

.empty-icon {
  margin-bottom: 16px;
  color: #444;
}

.empty-state p {
  font-size: 16px;
  margin-bottom: 16px;
}

.browse-link {
  padding: 10px 24px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  text-decoration: none;
  cursor: pointer;
  transition: background 0.2s;
}

.browse-link:hover {
  background: #1976D2;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.history-item {
  display: flex;
  gap: 16px;
  padding: 16px;
  background: #1a1a1a;
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.2s;
}

.history-item:hover {
  background: #252525;
}

.thumbnail-wrapper {
  position: relative;
  width: 160px;
  height: 90px;
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}

.thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.duration {
  position: absolute;
  bottom: 4px;
  right: 4px;
  padding: 2px 6px;
  background: rgba(0, 0, 0, 0.8);
  border-radius: 4px;
  font-size: 11px;
  color: #fff;
}

.progress-bar {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: rgba(255, 255, 255, 0.2);
}

.progress-fill {
  height: 100%;
  background: #f44336;
}

.video-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.video-title {
  font-size: 16px;
  font-weight: 500;
  color: #fff;
  margin: 0 0 8px 0;
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.video-meta {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: #999;
}

.progress-text {
  color: #f44336;
}

.actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
  justify-content: center;
}

.continue-btn {
  padding: 8px 16px;
  background: #2196F3;
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.2s;
}

.continue-btn:hover {
  background: #1976D2;
}

.delete-btn {
  width: 36px;
  height: 36px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: #666;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.delete-btn:hover {
  background: rgba(244, 67, 54, 0.1);
  color: #f44336;
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
  .history-page {
    padding: 16px;
  }

  .page-title {
    font-size: 22px;
  }

  .history-item {
    flex-direction: column;
    gap: 12px;
  }

  .thumbnail-wrapper {
    width: 100%;
    height: auto;
    aspect-ratio: 16 / 9;
  }

  .actions {
    flex-direction: row;
    justify-content: flex-end;
  }
}
</style>
