<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Gallery } from '../types'
import { useUserStore } from '../stores/userStore'
import { useGalleryStore } from '../stores/galleryStore'

const props = defineProps<{
  gallery: Gallery
  size?: 'large' | 'normal' | 'small'
  selectable?: boolean
  selected?: boolean
  editable?: boolean
}>()

const emit = defineEmits<{
  click: [gallery: Gallery]
  toggleSelect: [gallery: Gallery]
  edit: [gallery: Gallery]
  tagClick: [tag: any]
}>()

const userStore = useUserStore()
const galleryStore = useGalleryStore()

const thumbnailUrl = ref('')
const isLoading = ref(true)
const hasError = ref(false)

const withToken = (url: string) => {
  if (!url) return ''
  return userStore.token ? `${url}?token=${userStore.token}` : url
}

const loadThumb = () => {
  const base = props.gallery.cover_url
  if (!base) {
    thumbnailUrl.value = '/placeholder.jpg'
    isLoading.value = false
    return
  }
  thumbnailUrl.value = withToken(base)
  isLoading.value = false
}
loadThumb()
watch(() => props.gallery.hash, loadThumb)

const handleLike = (e: Event) => {
  e.stopPropagation()
  galleryStore.interact(props.gallery.hash, 'like')
}
const handleFavorite = (e: Event) => {
  e.stopPropagation()
  galleryStore.interact(props.gallery.hash, 'favorite')
}
const handleDislike = (e: Event) => {
  e.stopPropagation()
  galleryStore.interact(props.gallery.hash, 'dislike')
}

const cardStyle = computed(() => {
  const map = { large: { height: '180px' }, normal: { height: '135px' }, small: { height: '101px' } }
  return map[props.size || 'normal']
})

const progressPercent = computed(() => Math.round((props.gallery.progress || 0) * 100))

const handleClick = () => {
  if (props.selectable) {
    emit('toggleSelect', props.gallery)
    return
  }
  if (props.editable) {
    emit('edit', props.gallery)
    return
  }
  emit('click', props.gallery)
}
</script>

<template>
  <div class="gallery-card" @click="handleClick" :data-hash="gallery.hash">
    <div class="thumbnail-container" :style="{ height: cardStyle.height }">
      <div v-if="isLoading" class="thumbnail-loading"><div class="loading-spinner"></div></div>
      <img
        v-show="!isLoading"
        :src="thumbnailUrl"
        :alt="gallery.title"
        loading="lazy"
        class="thumbnail"
        :class="{ 'thumbnail-error': hasError }"
        @error="hasError = true; thumbnailUrl = '/placeholder.jpg'"
      />
      <span class="page-count" v-if="gallery.page_count">{{ gallery.page_count }}P</span>
      <!-- 编辑入口 -->
      <button
        v-if="editable"
        class="edit-overlay"
        @click.stop="emit('edit', gallery)"
        title="编辑"
        data-testid="card-edit"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>
        </svg>
      </button>
      <div class="continue-badge" v-if="(gallery.progress || 0) > 0 && (gallery.progress || 0) < 1">
        续读 {{ progressPercent }}%
      </div>
      <div class="continue-progress" v-if="(gallery.progress || 0) > 0">
        <div class="continue-progress-bar" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <div class="card-actions">
        <button class="card-action-btn like-action" :class="{ active: gallery.is_liked }" @click="handleLike" title="点赞">
          <svg width="18" height="18" viewBox="0 0 24 24" :fill="gallery.is_liked ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
        </button>
        <button class="card-action-btn favorite-action" :class="{ active: gallery.is_favorited }" @click="handleFavorite" title="收藏">
          <svg width="18" height="18" viewBox="0 0 24 24" :fill="gallery.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
        </button>
        <button class="card-action-btn dislike-action" :class="{ active: gallery.is_disliked }" @click="handleDislike" title="我不喜欢">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
          </svg>
        </button>
      </div>
    </div>
    <div class="gallery-info">
      <h3 class="title" :title="gallery.title">{{ gallery.title }}</h3>
      <div class="meta">
        <span class="views">{{ gallery.page_count }} 页</span>
        <span class="likes" v-if="gallery.like_count > 0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
          {{ gallery.like_count }}
        </span>
      </div>
      <!-- 标签：正常模式下点击跳转到该标签筛选 -->
      <div v-if="!editable && gallery.tags && gallery.tags.length" class="card-tags">
        <span
          v-for="t in gallery.tags"
          :key="t.id"
          class="card-tag"
          :title="'筛选: ' + t.name"
          @click.stop="emit('tagClick', t)"
        >{{ t.name }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.gallery-card { cursor: pointer; transition: transform 0.2s ease; width: 100%; position: relative; }
.gallery-card:hover { transform: scale(1.02); }
.thumbnail-container { position: relative; overflow: hidden; border-radius: 8px; background: #1a1a1a; width: 100%; }
.thumbnail { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumbnail-error { opacity: 0.5; }
.thumbnail-loading { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; background: #1a1a1a; }
.loading-spinner { width: 24px; height: 24px; border: 2px solid #333; border-top-color: #2196F3; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.page-count { position: absolute; bottom: 8px; right: 8px; background: rgba(0,0,0,0.7); color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.continue-badge { position: absolute; top: 8px; left: 8px; background: rgba(33,150,243,0.85); color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
.continue-progress { position: absolute; left: 0; bottom: 0; width: 100%; height: 4px; background: rgba(0,0,0,0.5); }
.continue-progress-bar { height: 100%; background: #2196F3; }
.card-actions { position: absolute; right: 8px; top: 8px; display: flex; gap: 6px; z-index: 2; }
.card-action-btn { width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,0.55); border: none; border-radius: 50%; color: #fff; cursor: pointer; transition: all 0.2s ease; }
.card-action-btn:hover { background: rgba(0,0,0,0.8); }
.like-action:hover, .like-action.active { color: #ff4757; }
.like-action.active { background: rgba(255,71,87,0.2); }
.favorite-action:hover, .favorite-action.active { color: #ffa502; }
.favorite-action.active { background: rgba(255,165,2,0.2); }
.dislike-action:hover, .dislike-action.active { color: #ffd93d; }
.dislike-action.active { background: rgba(255,217,61,0.2); }
.gallery-info { padding: 8px 0; }
.title { font-size: 14px; font-weight: 500; color: #fff; margin: 0 0 4px 0; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; line-clamp: 2; height: 40px; }
.meta { display: flex; gap: 12px; font-size: 12px; color: #999; }
.likes { display: flex; align-items: center; gap: 4px; color: #ff6b6b; }

.edit-overlay {
  position: absolute;
  top: 8px;
  left: 8px;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  background: rgba(33, 150, 243, 0.85);
  border: none;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 4;
}
.edit-overlay:hover { background: #2196F3; }
.card-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.card-tag {
  display: inline-block;
  padding: 2px 8px;
  background: #2a2a2a;
  border: 1px solid #3a3a3a;
  border-radius: 12px;
  color: #9ecbff;
  font-size: 11px;
  cursor: pointer;
}
.card-tag:hover { background: #2196F3; color: #fff; }
</style>
