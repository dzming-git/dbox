<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const favorites = ref<any[]>([])
const loading = ref(false)

onMounted(() => {
  loading.value = true
  // 从localStorage加载收藏列表
  const stored = localStorage.getItem('favorites')
  if (stored) {
    favorites.value = JSON.parse(stored)
  }
  loading.value = false
})

// 跳转到视频详情
const goToVideo = (hash: string) => {
  router.push(`/video/${hash}`)
}

// 取消收藏
const unfavorite = (hash: string, event: Event) => {
  event.stopPropagation()
  
  // 从收藏列表移除
  favorites.value = favorites.value.filter(f => f.hash !== hash)
  localStorage.setItem('favorites', JSON.stringify(favorites.value))
  
  // 同步更新favoritedVideos
  const favoritedVideos = JSON.parse(localStorage.getItem('favoritedVideos') || '[]')
  const index = favoritedVideos.indexOf(hash)
  if (index > -1) {
    favoritedVideos.splice(index, 1)
    localStorage.setItem('favoritedVideos', JSON.stringify(favoritedVideos))
  }
  
  showToast('已取消收藏')
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
  return date.toLocaleDateString('zh-CN')
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
  <div class="favorites-page">
    <div class="page-header">
      <h1 class="page-title">我的收藏</h1>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 空状态 -->
    <div v-else-if="favorites.length === 0" class="empty-state" data-testid="empty-state">
      <svg class="empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
      </svg>
      <p>暂无收藏视频</p>
      <router-link to="/" class="browse-link">去浏览视频</router-link>
    </div>

    <!-- 收藏列表 -->
    <div v-else class="favorites-grid">
      <div 
        v-for="video in favorites" 
        :key="video.hash"
        class="favorite-card"
        @click="goToVideo(video.hash)"
        data-testid="video-card"
      >
        <div class="thumbnail-wrapper">
          <img 
            :src="video.thumbnail || '/default-thumb.jpg'" 
            :alt="video.title"
            class="thumbnail"
          />
          <span v-if="video.duration" class="duration">{{ formatDuration(video.duration) }}</span>
        </div>
        <div class="video-info">
          <h3 class="video-title">{{ video.title }}</h3>
          <div class="video-meta">
            <span class="favorited-date">收藏于 {{ formatDate(video.favorited_at) }}</span>
          </div>
        </div>
        <button 
          class="unfavorite-btn" 
          @click="unfavorite(video.hash, $event)"
          data-testid="unfavorite-button"
          title="取消收藏"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Toast 提示 -->
    <div v-if="showToastFlag" class="toast" data-testid="unfavorite-success">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.favorites-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  min-height: 100vh;
  background: #0f0f0f;
  color: #fff;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 28px;
  font-weight: 600;
  margin: 0;
  color: #fff;
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

.favorites-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.favorite-card {
  background: #1a1a1a;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  position: relative;
}

.favorite-card:hover {
  transform: translateY(-4px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
}

.thumbnail-wrapper {
  position: relative;
  aspect-ratio: 16 / 9;
  overflow: hidden;
}

.thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
  transition: transform 0.3s;
}

.favorite-card:hover .thumbnail {
  transform: scale(1.05);
}

.duration {
  position: absolute;
  bottom: 8px;
  right: 8px;
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.8);
  border-radius: 4px;
  font-size: 12px;
  color: #fff;
}

.video-info {
  padding: 16px;
}

.video-title {
  font-size: 15px;
  font-weight: 500;
  color: #fff;
  margin: 0 0 8px 0;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.video-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #999;
}

.unfavorite-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 36px;
  height: 36px;
  background: rgba(0, 0, 0, 0.6);
  border: none;
  border-radius: 50%;
  color: #f44336;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s, background 0.2s;
}

.favorite-card:hover .unfavorite-btn {
  opacity: 1;
}

.unfavorite-btn:hover {
  background: rgba(244, 67, 54, 0.2);
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
  .favorites-page {
    padding: 16px;
  }

  .page-title {
    font-size: 22px;
  }

  .favorites-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }

  .unfavorite-btn {
    opacity: 1;
  }
}
</style>
