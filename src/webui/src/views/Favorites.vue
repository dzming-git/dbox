<script setup lang="ts">
import { ref, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { videoApi, galleryApi } from '../api'
import { fetchFavorites, type MediaItem } from '../utils/media'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import MediaCard from '../components/MediaCard.vue'

const router = useRouter()
const favorites = ref<MediaItem[]>([])
const loading = ref(false)

// 收藏夹分组
const collections = ref<any[]>([])
const activeCollectionId = ref<number | null>(null)  // null = 全部收藏
const openMenuItem = ref<MediaItem | null>(null)  // 当前展开"加入收藏夹"菜单的资源

// 加载收藏夹列表
const loadCollections = async () => {
  try {
    const r = await videoApi.getCollections() as any
    collections.value = (r && r.success && r.collections) ? r.collections : []
  } catch (e) {
    collections.value = []
  }
}

// 将收藏夹接口返回的视频/图集条目统一为 MediaItem
const toMediaItem = (it: any): MediaItem => {
  if (it.type === 'gallery') {
    return {
      type: 'gallery', hash: it.hash, title: it.title, cover: it.cover_url || '',
      pageCount: it.page_count, progress: it.progress, page: it.page ?? it.last_page,
      date: it.favorited_at, raw: it
    }
  }
  return {
    type: 'video', hash: it.hash, title: it.title, cover: it.thumbnail || '',
    thumbnail: it.thumbnail, duration: it.duration, progress: it.progress,
    date: it.favorited_at, raw: it
  }
}

// 加载当前显示的收藏（全部 或 某收藏夹，均含视频与图集）
const loadFavorites = async () => {
  loading.value = true
  try {
    let list: MediaItem[] = []
    if (activeCollectionId.value) {
      const r = await videoApi.getCollectionVideos(activeCollectionId.value) as any
      list = (r && r.success && Array.isArray(r.videos))
        ? r.videos.map(toMediaItem) : []
    } else {
      list = await fetchFavorites()
    }
    favorites.value = list
  } catch (e) {
    console.error('加载收藏失败:', e)
    favorites.value = []
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadCollections()
  await loadFavorites()
})

// 顶部下拉刷新：重新加载收藏夹与收藏内容
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(async () => {
    await loadCollections()
    await loadFavorites()
  })
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())

// 切换收藏夹
const selectCollection = async (id: number | null) => {
  activeCollectionId.value = id
  openMenuItem.value = null
  await loadFavorites()
}

// 新建收藏夹
const createCollection = async () => {
  const name = prompt('请输入收藏夹名称')
  if (!name || !name.trim()) return
  try {
    const r = await videoApi.createCollection(name.trim()) as any
    if (r && r.success) {
      await loadCollections()
      await selectCollection(r.collection.id)
    }
  } catch (e) {
    console.error('创建收藏夹失败', e)
  }
}

// 删除收藏夹
const deleteCollection = async (id: number, event: Event) => {
  event.stopPropagation()
  if (!confirm('确定删除该收藏夹吗？（其中的内容不会被取消收藏）')) return
  try {
    const r = await videoApi.deleteCollection(id) as any
    if (r && r.success) {
      await loadCollections()
      if (activeCollectionId.value === id) await selectCollection(null)
    }
  } catch (e) {
    console.error('删除收藏夹失败', e)
  }
}

// 取消收藏（视频/图集分别走各自接口，toggle 语义一致）
const onAction = async (payload: { name: string; item: MediaItem }) => {
  const { name, item } = payload
  if (name === 'unfavorite') {
    try {
      if (item.type === 'gallery') await galleryApi.interact(item.hash, 'favorite')
      else await videoApi.favoriteVideo(item.hash)
    } catch (e) {
      console.error('取消收藏失败:', e)
    }
    await loadFavorites()
    showToast('已取消收藏')
  } else if (name === 'addCollection') {
    openMenuItem.value = openMenuItem.value === item ? null : item
  }
}

const addToCollection = async (colId: number, item: MediaItem, event: Event) => {
  event.stopPropagation()
  try {
    await videoApi.addToCollection(colId, item.type, item.hash)
    showToast('已加入收藏夹')
  } catch (e) {
    console.error('加入收藏夹失败', e)
  }
  openMenuItem.value = null
}

// 提示消息
const toastMessage = ref('')
const showToastFlag = ref(false)
const showToast = (message: string) => {
  toastMessage.value = message
  showToastFlag.value = true
  setTimeout(() => { showToastFlag.value = false }, 2000)
}
</script>

<template>
  <div class="favorites-page">
    <div class="favorites-layout">
      <!-- 收藏夹侧边栏 -->
      <aside class="collections-sidebar">
        <div class="sidebar-header">
          <span>收藏夹</span>
          <button class="add-collection-btn" @click="createCollection" title="新建收藏夹">+</button>
        </div>
        <ul class="collection-list">
          <li
            class="collection-item"
            :class="{ active: activeCollectionId === null }"
            @click="selectCollection(null)"
          >
            <span class="collection-name">全部收藏</span>
          </li>
          <li
            v-for="col in collections"
            :key="col.id"
            class="collection-item"
            :class="{ active: activeCollectionId === col.id }"
            @click="selectCollection(col.id)"
          >
            <span class="collection-name">{{ col.name }}</span>
            <span class="collection-count">{{ col.video_count }}</span>
            <button class="del-collection-btn" @click="deleteCollection(col.id, $event)" title="删除收藏夹">×</button>
          </li>
        </ul>
      </aside>

      <!-- 主内容区 -->
      <div class="favorites-main">
        <div class="page-header">
          <h1 class="page-title">
            {{ activeCollectionId ? (collections.find(c => c.id === activeCollectionId)?.name || '收藏夹') : '我的收藏' }}
          </h1>
        </div>

        <div v-if="loading" class="loading-container">
          <div class="spinner"></div>
          <p>加载中...</p>
        </div>

        <div v-else-if="favorites.length === 0" class="empty-state" data-testid="empty-state">
          <svg class="empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
          </svg>
          <p>暂无收藏内容</p>
        </div>

        <div v-else class="favorites-grid">
          <div
            v-for="item in favorites"
            :key="item.type + ':' + item.hash"
            class="favorite-card-wrap"
          >
            <MediaCard :item="item" :show-type-badge="false" />
            <!-- 操作栏：放在卡片下方，避免缩略图上出现操作按钮，与首页展示逻辑一致 -->
            <div class="card-actions-row">
              <button class="action-text-btn unfavorite" @click.stop="onAction({ name: 'unfavorite', item })" title="取消收藏">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
                </svg>
                取消收藏
              </button>
              <button class="action-text-btn add-collection" @click.stop="onAction({ name: 'addCollection', item })" title="加入收藏夹">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                </svg>
                加入收藏夹
              </button>
            </div>
            <!-- 加入收藏夹 -->
            <div
              v-if="openMenuItem === item"
              class="collection-menu"
              @click.stop
            >
              <div class="collection-menu-title">加入收藏夹</div>
              <div v-if="collections.length === 0" class="collection-menu-empty">暂无收藏夹，请先新建</div>
              <div
                v-for="col in collections"
                :key="col.id"
                class="collection-menu-item"
                @click="addToCollection(col.id, item, $event)"
              >{{ col.name }}</div>
            </div>
          </div>
        </div>

        <div v-if="showToastFlag" class="toast" data-testid="toast">
          {{ toastMessage }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.favorites-page {
  padding: 24px;
  max-width: 1400px;
  margin: 0 auto;
  min-height: 100vh;
  background: var(--bg-surface);
  color: var(--text-primary);
}
.favorites-layout {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}
.collections-sidebar {
  width: 200px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 12px;
  position: sticky;
  top: 80px;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 12px;
  border-bottom: 1px solid var(--border-default);
  margin-bottom: 8px;
  font-size: 14px;
  color: var(--text-secondary);
}
.add-collection-btn {
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: var(--accent);
  color: var(--text-on-accent);
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
}
.add-collection-btn:hover { background: var(--accent-active); }
.collection-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.collection-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: background 0.2s;
}
.collection-item:hover { background: var(--bg-surface-hover); }
.collection-item.active { background: var(--accent); color: var(--text-on-accent); }
.collection-name {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.collection-count { font-size: 11px; color: var(--text-secondary); }
.collection-item.active .collection-count { color: rgba(255, 255, 255, 0.8); }
.del-collection-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 16px;
  cursor: pointer;
  line-height: 1;
  padding: 0 2px;
}
.del-collection-btn:hover { color: var(--danger); }
.favorites-main { flex: 1; min-width: 0; }
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
  border-top-color: var(--accent);
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
.favorites-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 20px;
}
.favorite-card-wrap { position: relative; }
.card-actions-row {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}
.action-text-btn {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 6px 0;
  border: 1px solid var(--border-default);
  border-radius: 6px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 12px;
  cursor: pointer;
  transition: background 0.2s, color 0.2s, border-color 0.2s;
}
.action-text-btn:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-strong);
}
.action-text-btn.unfavorite:hover {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
}
.action-text-btn.add-collection:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.collection-menu {
  position: absolute;
  top: 50px;
  right: 8px;
  width: 180px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  padding: 6px;
  z-index: 10;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}
.collection-menu-title {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 4px 8px 8px;
  border-bottom: 1px solid var(--border-default);
  margin-bottom: 4px;
}
.collection-menu-empty { font-size: 12px; color: var(--text-tertiary); padding: 6px 8px; }
.collection-menu-item {
  padding: 8px;
  border-radius: 6px;
  font-size: 13px;
  color: var(--text-primary);
  cursor: pointer;
}
.collection-menu-item:hover { background: var(--accent); color: var(--text-on-accent); }
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
  .favorites-page { padding: 16px; }
  .favorites-layout { flex-direction: column; }
  .collections-sidebar { width: 100%; position: static; }
  .page-title { font-size: 22px; }
  .favorites-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
}
</style>
