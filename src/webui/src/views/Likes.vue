<script setup lang="ts">
import { ref, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { videoApi, galleryApi } from '../api'
import { fetchLikes, type MediaItem } from '../utils/media'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import MediaCard from '../components/MediaCard.vue'

const likes = ref<MediaItem[]>([])
const loading = ref(false)

// 同时加载视频与图集的点赞列表（后端为唯一数据源，登录用户绑定账号）
const loadLikes = async () => {
  loading.value = true
  try {
    likes.value = await fetchLikes()
  } catch (e) {
    console.error('加载点赞列表失败:', e)
    likes.value = []
  } finally {
    loading.value = false
  }
}

onMounted(loadLikes)

// 顶部下拉刷新：重新加载点赞列表
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(loadLikes)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())

const onAction = async (payload: { name: string; item: MediaItem }) => {
  const { name, item } = payload
  if (name !== 'unlike') return
  try {
    if (item.type === 'gallery') await galleryApi.interact(item.hash, 'like')
    else await videoApi.likeVideo(item.hash)
  } catch (e) {
    console.error('取消点赞失败:', e)
  }
  await loadLikes()
  showToast('已取消点赞')
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
  <div class="likes-page">
    <div class="page-header">
      <h1 class="page-title">我的点赞</h1>
    </div>

    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <div v-else-if="likes.length === 0" class="empty-state" data-testid="empty-state">
      <svg class="empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
        <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
      </svg>
      <p>暂无点赞内容</p>
    </div>

    <div v-else class="likes-grid">
      <div
        v-for="item in likes"
        :key="item.type + ':' + item.hash"
        class="like-card-wrap"
      >
        <MediaCard
          :item="item"
          :show-type-badge="false"
          data-testid="video-card"
        />
        <button class="unlike-btn" @click.stop="onAction({ name: 'unlike', item })" title="取消点赞">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
          取消点赞
        </button>
      </div>
    </div>

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
  background: var(--bg-surface);
  color: var(--text-primary);
}
.page-header { margin-bottom: 24px; }
.page-title { font-size: 28px; font-weight: 600; margin: 0; color: var(--text-primary); }
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
  border-top-color: #ff4757;
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
.likes-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}
.like-card-wrap { position: relative; }
.unlike-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  width: 100%;
  margin-top: 8px;
  padding: 6px 0;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}
.unlike-btn:hover {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
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
  .likes-page { padding: 16px; }
  .page-title { font-size: 22px; }
  .likes-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
}
</style>
