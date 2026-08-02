<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Gallery } from '../types'
import { useUserStore } from '../stores/userStore'
import { useGalleryStore } from '../stores/galleryStore'
import WatchLaterButton from './WatchLaterButton.vue'

const props = defineProps<{
  gallery: Gallery
  size?: 'large' | 'normal' | 'small'
  selectable?: boolean
  selected?: boolean
}>()

const emit = defineEmits<{
  click: [gallery: Gallery]
  toggleSelect: [gallery: Gallery]
  tagClick: [tag: any]
}>()

const userStore = useUserStore()
const galleryStore = useGalleryStore()

const thumbnailUrl = ref('')
const isLoading = ref(true)
const hasError = ref(false)

const withToken = (url: string) => {
  if (!url) return ''
  const sep = url.includes('?') ? '&' : '?'
  return userStore.token ? `${url}${sep}token=${userStore.token}` : url
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
      <div class="continue-badge" v-if="(gallery.progress || 0) > 0 && (gallery.progress || 0) < 1">
        续读 {{ progressPercent }}%
      </div>
      <div class="continue-progress" v-if="(gallery.progress || 0) > 0">
        <div class="continue-progress-bar" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <WatchLaterButton
        variant="overlay"
        type="gallery"
        :id="gallery.hash"
        :title="gallery.title"
        :thumbnail="gallery.cover_url"
      />
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
      <div v-if="gallery.tags && gallery.tags.length" class="card-tags">
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
.gallery-card { cursor: pointer; transition: transform var(--transition); width: 100%; position: relative; }
.gallery-card:hover { transform: scale(1.02); }
.thumbnail-container { position: relative; overflow: hidden; border-radius: var(--radius-md); background: var(--bg-input); width: 100%; }
.thumbnail { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumbnail-error { opacity: 0.5; }
.thumbnail-loading { width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; background: var(--bg-input); }
.loading-spinner { width: 24px; height: 24px; border: 2px solid var(--border-strong); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.page-count { position: absolute; bottom: 8px; right: 8px; background: rgba(0,0,0,0.7); backdrop-filter: blur(4px); color: var(--text-on-accent); padding: 2px 6px; border-radius: var(--radius-sm); font-size: 12px; font-weight: 500; }
.continue-badge { position: absolute; top: 8px; left: 8px; background: var(--info); color: var(--text-on-accent); padding: 2px 8px; border-radius: var(--radius-pill); font-size: 11px; font-weight: 600; }
.continue-progress { position: absolute; left: 0; bottom: 0; width: 100%; height: 4px; background: rgba(0,0,0,0.5); }
.continue-progress-bar { height: 100%; background: var(--info); }
.gallery-info { padding: 8px 0; }
.title { font-size: 14px; font-weight: 500; color: var(--text-primary); margin: 0 0 4px 0; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; line-clamp: 2; height: 40px; }
.meta { display: flex; gap: 12px; font-size: 12px; color: var(--text-tertiary); }
.likes { display: flex; align-items: center; gap: 4px; color: var(--danger); }

.edit-overlay {
  position: absolute;
  top: 8px;
  left: 8px;
  width: 28px;
  height: 28px;
  border-radius: var(--radius-sm);
  background: var(--accent);
  border: none;
  color: var(--text-on-accent);
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  z-index: 4;
}
.edit-overlay:hover { background: var(--accent-hover); }
.card-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.card-tag {
  display: inline-block;
  padding: 2px 8px;
  background: var(--accent-soft);
  border: 1px solid var(--accent-border);
  border-radius: var(--radius-pill);
  color: var(--accent);
  font-size: 11px;
  cursor: pointer;
  transition: background var(--transition-fast);
}
.card-tag:hover { background: var(--accent-soft-hover); color: var(--accent); }
</style>
