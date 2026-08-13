<script setup lang="ts">
import { ref, onMounted, computed, onActivated, onDeactivated, onUnmounted } from 'vue'
import { videoApi, galleryApi } from '../api'
import { fetchDisliked, type MediaItem } from '../utils/media'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import MediaCard from '../components/MediaCard.vue'
import { useUserStore } from '../stores/userStore'

const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin)
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

// 顶部下拉刷新：重新加载「我不喜欢」列表
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(loadDisliked)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())

// 管理员可见的操作：删除（永久删除资源）+ 普通用户的取消屏蔽
const cardActions = computed(() => (isAdmin.value ? ['restore', 'delete'] : ['restore']))

// 格式化文件大小
const formatSize = (bytes?: number) => {
  if (!bytes || bytes <= 0) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = bytes
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

// 截断磁盘路径，仅显示末尾
const shortPath = (p?: string) => {
  if (!p) return ''
  return p.length > 48 ? '…' + p.slice(-48) : p
}

// 取消不喜欢（撤销屏蔽），或管理员永久删除资源
const onAction = async (payload: { name: string; item: MediaItem }) => {
  const { name, item } = payload
  if (name === 'restore') {
    try {
      if (item.type === 'gallery') await galleryApi.interact(item.hash, 'dislike')
      else await videoApi.dislikeVideo(item.hash)
    } catch (e) {
      console.error('取消不喜欢失败:', e)
    }
    await loadDisliked()
    showToast('已取消屏蔽')
    return
  }
  if (name === 'delete') {
    if (!confirm(`确定要永久删除「${item.title}」吗？此操作不可恢复。`)) return
    try {
      if (item.type === 'gallery') await galleryApi.deleteGallery(item.hash, true)
      else await videoApi.deleteVideo(item.hash, true)
      await loadDisliked()
      showToast('已永久删除')
    } catch (e) {
      console.error('删除失败:', e)
      showToast('删除失败')
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
    </div>

    <div v-else class="disliked-grid">
      <div
        v-for="item in disliked"
        :key="item.type + ':' + item.hash"
        class="disliked-card-wrap"
      >
        <MediaCard
          :item="item"
          :actions="cardActions"
          @action="onAction"
          data-testid="video-card"
        />
        <div v-if="isAdmin && (item.location || item.size)" class="admin-meta">
          <div v-if="item.location" class="meta-line" :title="item.location">
            <span class="meta-label">位置</span>{{ shortPath(item.location) }}
          </div>
          <div v-if="item.size" class="meta-line">
            <span class="meta-label">大小</span>{{ formatSize(item.size) }}
          </div>
        </div>
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
  background: var(--bg-surface);
  color: var(--text-primary);
}
.page-header { margin-bottom: 24px; }
.page-title { font-size: 28px; font-weight: 600; margin: 0; color: var(--text-primary); }
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
  .disliked-grid { grid-template-columns: repeat(1, 1fr); gap: 12px; }
}
/* 管理员可见的资源位置与大小（权限控制） */
.admin-meta {
  margin: -8px 12px 12px;
  padding: 8px 10px;
  background: var(--bg-base);
  border: 1px solid var(--border-default);
  border-radius: 0 0 10px 10px;
  font-size: 12px;
  color: var(--text-secondary);
}
.meta-line {
  display: flex;
  gap: 6px;
  align-items: baseline;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta-label {
  flex-shrink: 0;
  color: var(--text-tertiary);
  font-weight: 600;
}
</style>
