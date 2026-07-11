<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { videoApi } from '../api'

const router = useRouter()
const disliked = ref<any[]>([])
const loading = ref(false)

// 从后端加载当前用户标记为不喜欢的视频列表
const loadDisliked = async () => {
  loading.value = true
  try {
    const response = await videoApi.getDisliked() as any
    disliked.value = (response && response.success && response.videos) ? response.videos : []
  } catch (e) {
    console.error('加载不喜欢列表失败:', e)
    disliked.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadDisliked)

const goToVideo = (hash: string) => {
  router.push(`/video/${hash}`)
}

// 取消不喜欢（撤销屏蔽），调后端切换状态
const restore = async (hash: string, event: Event) => {
  event.stopPropagation()
  try {
    await videoApi.dislikeVideo(hash)
  } catch (e) {
    console.error('取消不喜欢失败:', e)
  }
  await loadDisliked()
  showToast('已取消屏蔽')
}

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

const formatDate = (dateStr: string): string => {
  const date = new Date(dateStr)
  return date.toLocaleDateString('zh-CN')
}

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
  <div class="disliked-page">
    <div class="page-header">
      <h1 class="page-title">我不喜欢</h1>
      <p class="page-sub">这里列出你标记为"我不喜欢"的视频，默认已在首页屏蔽。点击可取消屏蔽。</p>
    </div>

    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="disliked.length === 0" class="empty-state" data-testid="empty-state">
      <svg class="empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
      </svg>
      <p>暂无屏蔽的视频</p>
      <router-link to="/" class="browse-link">去浏览视频</router-link>
    </div>

    <div v-else class="disliked-grid">
      <div
        v-for="video in disliked"
        :key="video.hash"
        class="disliked-card"
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
            <span class="disliked-date">屏蔽于 {{ formatDate(video.disliked_at) }}</span>
          </div>
        </div>
        <button
          class="restore-btn"
          @click="restore(video.hash, $event)"
          data-testid="restore-button"
          title="取消屏蔽"
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
            <path d="M3 3v5h5"/>
          </svg>
        </button>
      </div>
    </div>

    <div v-if="showToastFlag" class="toast" data-testid="restore-success">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.disliked-page {
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

.page-sub {
  margin: 8px 0 0;
  color: #888;
  font-size: 14px;
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
  border-top-color: #ffd93d;
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
  background: #ffd93d;
  border: none;
  border-radius: 8px;
  color: #222;
  font-size: 14px;
  text-decoration: none;
  cursor: pointer;
  transition: background 0.2s;
}

.browse-link:hover {
  background: #e6c233;
}

.disliked-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}

.disliked-card {
  background: #1a1a1a;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  position: relative;
}

.disliked-card:hover {
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

.disliked-card:hover .thumbnail {
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

.restore-btn {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 36px;
  height: 36px;
  background: rgba(0, 0, 0, 0.6);
  border: none;
  border-radius: 50%;
  color: #ffd93d;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0;
  transition: opacity 0.2s, background 0.2s;
}

.disliked-card:hover .restore-btn {
  opacity: 1;
}

.restore-btn:hover {
  background: rgba(255, 217, 61, 0.2);
}

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
  .disliked-page {
    padding: 16px;
  }

  .page-title {
    font-size: 22px;
  }

  .disliked-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }

  .restore-btn {
    opacity: 1;
  }
}
</style>
