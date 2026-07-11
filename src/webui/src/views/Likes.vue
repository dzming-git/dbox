<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { videoApi } from '../api'

const router = useRouter()
const likes = ref<any[]>([])
const loading = ref(false)

// 从后端加载当前用户点赞过的视频列表（以后端为唯一数据源，登录用户绑定账号，跨设备一致）
const loadLikes = async () => {
  loading.value = true
  try {
    const response = await videoApi.getLikes() as any
    likes.value = (response && response.success && response.videos) ? response.videos : []
  } catch (e) {
    console.error('加载点赞列表失败:', e)
    likes.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadLikes)

// 跳转到视频详情
const goToVideo = (hash: string) => {
  router.push(`/video/${hash}`)
}

// 取消点赞（调用后端接口切换状态，以后端为准）
const unlike = async (hash: string, event: Event) => {
  event.stopPropagation()
  try {
    await videoApi.likeVideo(hash)
  } catch (e) {
    console.error('取消点赞失败:', e)
  }
  // 重新拉取最新点赞列表
  await loadLikes()
  showToast('已取消点赞')
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
  <div class="likes-page">
    <div class="page-header">
      <h1 class="page-title">我的点赞</h1>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 空状态 -->
    <div v-else-if="likes.length === 0" class="empty-state" data-testid="empty-state">
      <svg class="empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
      </svg>
      <p>暂无点赞视频</p>
      <router-link to="/" class="browse-link">去浏览视频</router-link>
    </div>

    <!-- 点赞列表 -->
    <div v-else class="likes-grid">
      <div 
        v-for="video in likes" 
        :key="video.hash"
        class="like-card"
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
            <span class="liked-date">点赞于 {{ formatDate(video.liked_at) }}</span>
          </div>
        </div>
        <button 
          class="unlike-btn" 
          @click="unlike(video.hash, $event)"
          data-testid="unlike-button"
          title="取消点赞"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
        </button>
      </div>
    </div>

    <!-- Toast 提示 -->
    <div v-if="showToastFlag" class="toast" data-testid="unlike-success">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.likes-page {
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
  border-top-color: #ff4757;
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
  background: #ff4757;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  text-decoration: none;
  cursor: pointer;
  transition: background 0.2s;
}

.browse-link:hover {
  background: #e03e4c;
}

.likes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.like-card {
  background: #1a1a1a;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  position: relative;
}

.like-card:hover {
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

.like-card:hover .thumbnail {
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

.unlike-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 36px;
  height: 36px;
  background: rgba(0, 0, 0, 0.6);
  border: none;
  border-radius: 50%;
  color: #ff4757;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s, background 0.2s;
}

.like-card:hover .unlike-btn {
  opacity: 1;
}

.unlike-btn:hover {
  background: rgba(255, 71, 87, 0.2);
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
  .likes-page {
    padding: 16px;
  }

  .page-title {
    font-size: 22px;
  }

  .likes-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }

  .unlike-btn {
    opacity: 1;
  }
}
</style>
