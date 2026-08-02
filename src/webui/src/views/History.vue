<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchHistory, type MediaItem } from '../utils/media'
import { historyApi } from '../api'
import MediaCard from '../components/MediaCard.vue'

const router = useRouter()
const history = ref<MediaItem[]>([])
const loading = ref(false)

onMounted(async () => {
  loading.value = true
  try {
    history.value = await fetchHistory()
  } catch (e) {
    console.error('加载历史失败:', e)
    history.value = []
  } finally {
    loading.value = false
  }
})

// 视频与图集历史均以后端为唯一数据源，删除/清空走后端接口。
const onAction = async (payload: { name: string; item: MediaItem }) => {
  const { name, item } = payload
  if (name === 'continue') {
    if (item.type === 'video') {
      const seconds = Math.floor((item.progress || 0) * (item.duration || 0))
      router.push({ path: `/video/${item.hash}`, query: { t: seconds } })
    } else {
      router.push(`/gallery/${item.hash}`)
    }
  } else if (name === 'delete') {
    try {
      await historyApi.removeHistory(item.type, item.hash)
      history.value = history.value.filter(it => !(it.type === item.type && it.hash === item.hash))
      showToast('已删除观看记录')
    } catch (e) {
      console.error('删除历史失败:', e)
    }
  }
}

const clearAllHistory = async () => {
  if (confirm('确定要清空观看历史吗？（视频记录与图集阅读进度都会清空）')) {
    try {
      await historyApi.clearHistory()
      history.value = []
      showToast('已清空观看历史')
    } catch (e) {
      console.error('清空历史失败:', e)
    }
  }
}

const toastMessage = ref('')
const showToastFlag = ref(false)
const showToast = (message: string) => {
  toastMessage.value = message
  showToastFlag.value = true
  setTimeout(() => { showToastFlag.value = false }, 2000)
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

    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="history.length === 0" class="empty-state" data-testid="empty-state">
      <svg class="empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
      </svg>
      <p>暂无观看记录</p>
      <div class="browse-links">
        <router-link to="/" class="browse-link">去浏览视频</router-link>
        <router-link to="/galleries" class="browse-link gallery">去浏览图集</router-link>
      </div>
    </div>

    <div v-else class="history-grid">
      <MediaCard
        v-for="item in history"
        :key="item.type + ':' + item.hash"
        :item="item"
        :actions="['continue', 'delete']"
        @action="onAction"
        data-testid="history-item"
      />
    </div>

    <div v-if="showToastFlag" class="toast" data-testid="delete-success">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.history-page {
  padding: 24px;
  max-width: 1400px;
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
.page-title { font-size: 28px; font-weight: 600; margin: 0; color: #fff; }
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
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  color: #666;
}
.empty-icon { margin-bottom: 16px; color: #444; }
.empty-state p { font-size: 16px; margin-bottom: 16px; }
.browse-links { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; }
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
.browse-link:hover { background: #1976D2; }
.browse-link.gallery { background: #ff9800; }
.browse-link.gallery:hover { background: #e68a00; }
.history-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
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
  .history-page { padding: 16px; }
  .page-title { font-size: 22px; }
  .history-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
}
</style>
