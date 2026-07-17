<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import type { Comic } from '../types'
import { useUserStore } from '../stores/userStore'
import { useComicStore } from '../stores/comicStore'
import { comicApi } from '../api'

const props = defineProps<{
  comic: Comic
  size?: 'large' | 'normal' | 'small'
  selectable?: boolean
  selected?: boolean
}>()

const emit = defineEmits<{
  click: [comic: Comic]
  toggleSelect: [comic: Comic]
}>()

const userStore = useUserStore()
const comicStore = useComicStore()

const thumbnailUrl = ref('')
const isLoading = ref(true)
const hasError = ref(false)

const showPlaylistMenu = ref(false)
const playlists = ref<any[]>([])
const newPlaylistName = ref('')

const withToken = (url: string) => {
  if (!url) return ''
  return userStore.token ? `${url}?token=${userStore.token}` : url
}

const loadThumb = () => {
  const base = props.comic.cover_url
  if (!base) {
    thumbnailUrl.value = '/placeholder.jpg'
    isLoading.value = false
    return
  }
  thumbnailUrl.value = withToken(base)
  isLoading.value = false
}
loadThumb()
watch(() => props.comic.hash, loadThumb)

const handleLike = (e: Event) => {
  e.stopPropagation()
  comicStore.interact(props.comic.hash, 'like')
}
const handleFavorite = (e: Event) => {
  e.stopPropagation()
  comicStore.interact(props.comic.hash, 'favorite')
}
const handleDislike = (e: Event) => {
  e.stopPropagation()
  comicStore.interact(props.comic.hash, 'dislike')
}

const openPlaylistMenu = async (e: Event) => {
  e.stopPropagation()
  showPlaylistMenu.value = !showPlaylistMenu.value
  if (showPlaylistMenu.value) {
    try {
      const res: any = await comicApi.getPlaylists()
      playlists.value = res.playlists || []
    } catch {
      playlists.value = []
    }
  }
}
const addToPlaylist = async (pid: number, ev: Event) => {
  ev.stopPropagation()
  try {
    await comicApi.addToPlaylist(pid, props.comic.hash)
  } catch {
    /* ignore */
  }
  showPlaylistMenu.value = false
}
const createAndAdd = async (ev: Event) => {
  ev.stopPropagation()
  const name = newPlaylistName.value.trim()
  if (!name) return
  try {
    const res: any = await comicApi.createPlaylist({ name })
    if (res.success) {
      await comicApi.addToPlaylist(res.playlist.id, props.comic.hash)
      playlists.value.unshift(res.playlist)
    }
    newPlaylistName.value = ''
  } catch {
    /* ignore */
  }
  showPlaylistMenu.value = false
}

const cardStyle = computed(() => {
  const map = { large: { height: '180px' }, normal: { height: '135px' }, small: { height: '101px' } }
  return map[props.size || 'normal']
})

const progressPercent = computed(() => Math.round((props.comic.progress || 0) * 100))

const handleClick = () => {
  if (props.selectable) {
    emit('toggleSelect', props.comic)
    return
  }
  emit('click', props.comic)
}
</script>

<template>
  <div class="comic-card" :class="{ 'has-menu': showPlaylistMenu }" @click="handleClick" :data-hash="comic.hash">
    <div class="thumbnail-container" :style="{ height: cardStyle.height }">
      <div v-if="isLoading" class="thumbnail-loading"><div class="loading-spinner"></div></div>
      <img
        v-show="!isLoading"
        :src="thumbnailUrl"
        :alt="comic.title"
        loading="lazy"
        class="thumbnail"
        :class="{ 'thumbnail-error': hasError }"
        @error="hasError = true; thumbnailUrl = '/placeholder.jpg'"
      />
      <span class="page-count" v-if="comic.page_count">{{ comic.page_count }}P</span>
      <div class="continue-badge" v-if="(comic.progress || 0) > 0 && (comic.progress || 0) < 1">
        续读 {{ progressPercent }}%
      </div>
      <div class="continue-progress" v-if="(comic.progress || 0) > 0">
        <div class="continue-progress-bar" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <div class="card-actions">
        <button class="card-action-btn like-action" :class="{ active: comic.is_liked }" @click="handleLike" title="点赞">
          <svg width="18" height="18" viewBox="0 0 24 24" :fill="comic.is_liked ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
            <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
          </svg>
        </button>
        <button class="card-action-btn favorite-action" :class="{ active: comic.is_favorited }" @click="handleFavorite" title="收藏">
          <svg width="18" height="18" viewBox="0 0 24 24" :fill="comic.is_favorited ? 'currentColor' : 'none'" stroke="currentColor" stroke-width="2">
            <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
          </svg>
        </button>
        <button class="card-action-btn dislike-action" :class="{ active: comic.is_disliked }" @click="handleDislike" title="我不喜欢">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
          </svg>
        </button>
        <button class="card-action-btn playlist-action" :class="{ active: showPlaylistMenu }" @click="openPlaylistMenu" title="加入合集">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="5" y="11" width="14" height="9" rx="2"/>
            <path d="M8 11V7a4 4 0 0 1 8 0v4"/>
          </svg>
        </button>
      </div>
    </div>
    <div class="comic-info">
      <h3 class="title" :title="comic.title">{{ comic.title }}</h3>
      <div class="meta">
        <span class="views">{{ comic.page_count }} 页</span>
        <span class="likes" v-if="comic.like_count > 0">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
          {{ comic.like_count }}
        </span>
      </div>
    </div>

    <div v-if="showPlaylistMenu" class="playlist-popover-backdrop" @click="showPlaylistMenu = false"></div>
    <div v-if="showPlaylistMenu" class="playlist-popover" @click.stop>
      <div class="playlist-popover-title">加入合集</div>
      <div class="playlist-list">
        <button
          v-for="pl in playlists"
          :key="pl.id"
          class="playlist-item"
          @click="addToPlaylist(pl.id, $event)"
        >
          <span class="pl-name">{{ pl.name }}</span>
          <span class="pl-count">{{ pl.comic_count }}</span>
        </button>
        <div v-if="playlists.length === 0" class="playlist-empty">暂无合集</div>
      </div>
      <div class="playlist-new">
        <input
          v-model="newPlaylistName"
          class="playlist-new-input"
          placeholder="新建合集名称"
          @keyup.enter="createAndAdd($event)"
        />
        <button class="playlist-new-btn" @click="createAndAdd($event)">新建并加入</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.comic-card { cursor: pointer; transition: transform 0.2s ease; width: 100%; position: relative; }
.comic-card:hover { transform: scale(1.02); }
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
.playlist-action:hover, .playlist-action.active { color: #2196F3; }
.playlist-action.active { background: rgba(33,150,243,0.2); }
.comic-info { padding: 8px 0; }
.title { font-size: 14px; font-weight: 500; color: #fff; margin: 0 0 4px 0; overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; line-clamp: 2; height: 40px; }
.meta { display: flex; gap: 12px; font-size: 12px; color: #999; }
.likes { display: flex; align-items: center; gap: 4px; color: #ff6b6b; }

.playlist-popover-backdrop { position: fixed; inset: 0; z-index: 40; }
.playlist-popover { position: absolute; top: calc(100% - 6px); right: 0; left: 0; z-index: 50; background: #2a2a2a; border: 1px solid #3a3a3a; border-radius: 12px; padding: 12px; box-shadow: 0 12px 32px rgba(0,0,0,0.5); }
.playlist-popover-title { color: #fff; font-size: 13px; font-weight: 600; margin-bottom: 8px; }
.playlist-list { max-height: 180px; overflow-y: auto; display: flex; flex-direction: column; gap: 4px; margin-bottom: 8px; }
.playlist-item { display: flex; align-items: center; justify-content: space-between; padding: 8px 10px; background: #1f1f1f; border: 1px solid #333; border-radius: 8px; color: #eee; cursor: pointer; font-size: 13px; }
.playlist-item:hover { background: #2f2f2f; }
.pl-count { color: #888; font-size: 12px; }
.playlist-empty { color: #777; font-size: 13px; text-align: center; padding: 12px 0; }
.playlist-new { display: flex; gap: 6px; }
.playlist-new-input { flex: 1; min-width: 0; padding: 8px 10px; background: #1a1a1a; border: 1px solid #444; border-radius: 8px; color: #fff; font-size: 13px; }
.playlist-new-input:focus { outline: none; border-color: #2196F3; }
.playlist-new-btn { padding: 8px 12px; background: #2196F3; border: none; border-radius: 8px; color: #fff; font-size: 13px; cursor: pointer; white-space: nowrap; }
</style>
