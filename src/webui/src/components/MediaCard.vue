<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import type { MediaItem } from '../utils/media'

const props = defineProps<{
  item: MediaItem
  actions?: string[]   // 'unfavorite' | 'unlike' | 'restore' | 'continue' | 'delete' | 'addCollection'
}>()
const emit = defineEmits<{
  (e: 'open', item: MediaItem): void
  (e: 'action', payload: { name: string; item: MediaItem }): void
}>()

const router = useRouter()
const userStore = useUserStore()

const coverUrl = computed(() => {
  if (props.item.type === 'comic' && props.item.cover && userStore.token) {
    const sep = props.item.cover.includes('?') ? '&' : '?'
    return props.item.cover + sep + 'token=' + userStore.token
  }
  return props.item.cover || '/default-thumb.jpg'
})

const typeLabel = computed(() => (props.item.type === 'video' ? '视频' : '漫画'))
const subBadge = computed(() => {
  if (props.item.type === 'video') {
    return props.item.duration ? formatDuration(props.item.duration) : ''
  }
  return props.item.pageCount ? `${props.item.pageCount}P` : ''
})

const formatDuration = (seconds: number): string => {
  if (!seconds || isNaN(seconds)) return '00:00'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

const formatDate = (dateStr?: string): string => {
  if (!dateStr) return ''
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr
  return d.toLocaleDateString('zh-CN')
}

const onOpen = () => {
  if (props.item.type === 'video') router.push(`/video/${props.item.hash}`)
  else router.push(`/comic/${props.item.hash}`)
}
const onAction = (name: string, e: Event) => {
  e.stopPropagation()
  emit('action', { name, item: props.item })
}
</script>

<template>
  <div class="media-card" @click="onOpen" data-testid="media-card">
    <div class="thumbnail-wrapper">
      <img :src="coverUrl" :alt="item.title" class="thumbnail" @error="(e:any)=>e.target.src='/default-thumb.jpg'" />
      <span class="type-badge" :class="item.type">{{ typeLabel }}</span>
      <span v-if="subBadge" class="sub-badge">{{ subBadge }}</span>

      <button
        v-if="actions?.includes('addCollection')"
        class="action-btn add-collection"
        title="加入收藏夹"
        @click="onAction('addCollection', $event)"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
        </svg>
      </button>
      <button
        v-if="actions?.includes('unfavorite')"
        class="action-btn danger"
        title="取消收藏"
        @click="onAction('unfavorite', $event)"
        data-testid="unfavorite-button"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
        </svg>
      </button>
      <button
        v-if="actions?.includes('unlike')"
        class="action-btn danger"
        title="取消点赞"
        @click="onAction('unlike', $event)"
        data-testid="unlike-button"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
        </svg>
      </button>
      <button
        v-if="actions?.includes('restore')"
        class="action-btn warn"
        title="取消屏蔽"
        @click="onAction('restore', $event)"
        data-testid="restore-button"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>
          <path d="M3 3v5h5"/>
        </svg>
      </button>
    </div>

    <div class="media-info">
      <h3 class="media-title">{{ item.title }}</h3>
      <div class="media-meta">
        <span v-if="item.date">{{ formatDate(item.date) }}</span>
        <span v-if="item.type === 'comic' && item.progress" class="progress-text">
          看到 {{ Math.round(item.progress * 100) }}%
        </span>
      </div>
    </div>

    <div v-if="actions?.includes('continue') || actions?.includes('delete')" class="media-actions">
      <button
        v-if="actions?.includes('continue') && item.progress && item.progress > 0"
        class="continue-btn"
        @click="onAction('continue', $event)"
        data-testid="continue-button"
      >继续</button>
      <button
        v-if="actions?.includes('delete')"
        class="delete-btn"
        title="删除记录"
        @click="onAction('delete', $event)"
        data-testid="delete-history-button"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
          <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.media-card {
  background: #1a1a1a;
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.2s, box-shadow 0.2s;
  position: relative;
}
.media-card:hover {
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
.media-card:hover .thumbnail {
  transform: scale(1.05);
}
.type-badge {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: rgba(0, 0, 0, 0.6);
}
.type-badge.video { background: rgba(33, 150, 243, 0.85); }
.type-badge.comic { background: rgba(255, 152, 0, 0.85); }
.sub-badge {
  position: absolute;
  bottom: 8px;
  right: 8px;
  padding: 2px 8px;
  background: rgba(0, 0, 0, 0.8);
  border-radius: 4px;
  font-size: 12px;
  color: #fff;
}
.action-btn {
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
.media-card:hover .action-btn { opacity: 1; }
.action-btn.danger { color: #f44336; }
.action-btn.danger:hover { background: rgba(244, 67, 54, 0.2); }
.action-btn.warn { color: #ffd93d; right: 52px; }
.action-btn.warn:hover { background: rgba(255, 217, 61, 0.2); }
.action-btn.add-collection { color: #ffa502; right: 52px; }
.action-btn.add-collection:hover { background: rgba(255, 165, 2, 0.2); }
.media-info { padding: 16px; }
.media-title {
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
.media-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #999;
}
.progress-text { color: #f44336; }
.media-actions {
  position: absolute;
  bottom: 8px;
  right: 8px;
  display: flex;
  gap: 8px;
}
.continue-btn {
  padding: 6px 12px;
  background: #2196F3;
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}
.continue-btn:hover { background: #1976D2; }
.delete-btn {
  width: 34px;
  height: 34px;
  background: rgba(0, 0, 0, 0.6);
  border: none;
  border-radius: 50%;
  color: #aaa;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}
.delete-btn:hover { background: rgba(244, 67, 54, 0.2); color: #f44336; }
@media (max-width: 768px) {
  .action-btn { opacity: 1; }
}
</style>
