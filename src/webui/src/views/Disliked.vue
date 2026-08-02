<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { videoApi, galleryApi } from '../api'
import { fetchDisliked, type MediaItem } from '../utils/media'
import MediaCard from '../components/MediaCard.vue'

const disliked = ref<MediaItem[]>([])
const loading = ref(false)

// 同时加载视频与图集的"我不喜欢"列表
const loadDisliked = async () => {
  loading.value = true
  try {
    disliked.value = await fetchDisliked()
  } catch (e) {
    console.error('加载不喜欢列表失败:', e)
    disliked.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadDisliked)

// 取消不喜欢（撤销屏蔽），调后端切换状态
const onAction = async (payload: { name: string; item: MediaItem }) => {
  const { name, item } = payload
  if (name !== 'restore') return
  try {
    if (item.type === 'gallery') await galleryApi.interact(item.hash, 'dislike')
    else await videoApi.dislikeVideo(item.hash)
  } catch (e) {
    console.error('取消不喜欢失败:', e)
  }
  await loadDisliked()
  showToast('已取消屏蔽')
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
  <div class="disliked-page">
    <div class="page-header">
      <h1 class="page-title">我不喜欢</h1>
      <p class="page-sub">这里列出你标记为"我不喜欢"的内容，默认已在首页/图集库屏蔽。点击可取消屏蔽。</p>
    </div>

    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="disliked.length === 0" class="empty-state" data-testid="empty-state">
      <svg class="empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
      </svg>
      <p>暂无屏蔽的内容</p>
      <div class="browse-links">
        <router-link to="/" class="browse-link">去浏览视频</router-link>
        <router-link to="/galleries" class="browse-link gallery">去浏览图集</router-link>
      </div>
    </div>

    <div v-else class="disliked-grid">
      <MediaCard
        v-for="item in disliked"
        :key="item.type + ':' + item.hash"
        :item="item"
        :actions="['restore']"
        @action="onAction"
        data-testid="video-card"
      />
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
  background: var(--bg-surface);
  color: var(--text-on-accent);
}
.page-header { margin-bottom: 24px; }
.page-title { font-size: 28px; font-weight: 600; margin: 0; color: var(--text-on-accent); }
.page-sub { margin: 8px 0 0; color: var(--text-secondary); font-size: 14px; }
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
  border: 3px solid var(--border-default);
  border-top-color: #ffd93d;
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
  color: var(--text-tertiary);
}
.empty-icon { margin-bottom: 16px; color: var(--border-strong); }
.empty-state p { font-size: 16px; margin-bottom: 16px; }
.browse-links { display: flex; gap: 12px; flex-wrap: wrap; justify-content: center; }
.browse-link {
  padding: 10px 24px;
  background: #ffd93d;
  border: none;
  border-radius: 8px;
  color: var(--bg-surface-2);
  font-size: 14px;
  text-decoration: none;
  cursor: pointer;
  transition: background 0.2s;
}
.browse-link:hover { background: #e6c233; }
.browse-link.gallery { background: #ff9800; color: var(--text-on-accent); }
.browse-link.gallery:hover { background: #e68a00; }
.disliked-grid {
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
  color: var(--text-on-accent);
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
  .disliked-page { padding: 16px; }
  .page-title { font-size: 22px; }
  .disliked-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
}
</style>
