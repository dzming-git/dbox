<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { videoApi, comicApi } from '../api'
import type { MediaItem } from '../utils/media'

const route = useRoute()
const q = ref((route.query.q as string) || '')
const videoResults = ref<MediaItem[]>([])
const comicResults = ref<MediaItem[]>([])
const loading = ref(false)

const search = async () => {
  const query = q.value.trim()
  if (!query) {
    videoResults.value = []
    comicResults.value = []
    return
  }
  loading.value = true
  try {
    const [v, c] = await Promise.all([
      videoApi.getVideos({ search: query, limit: 60 }) as any,
      comicApi.getComics({ search: query, limit: 60 }) as any
    ])
    videoResults.value = (v?.videos || []).map((x: any) => ({
      type: 'video', hash: x.hash, title: x.title,
      cover: x.thumbnail || '', thumbnail: x.thumbnail, duration: x.duration, raw: x
    }))
    comicResults.value = (c?.comics || []).map((x: any) => ({
      type: 'comic', hash: x.hash, title: x.title,
      cover: x.cover_url || '', pageCount: x.page_count, raw: x
    }))
  } catch (e) {
    console.error('搜索失败:', e)
  } finally {
    loading.value = false
  }
}

let timer: number | null = null
watch(q, () => {
  if (timer) clearTimeout(timer)
  timer = window.setTimeout(search, 400)
})

onMounted(search)
</script>

<template>
  <div class="search-page">
    <div class="search-header">
      <div class="search-box">
        <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
        </svg>
        <input v-model="q" type="text" placeholder="搜索视频、漫画..." class="search-input" autofocus />
      </div>
      <p v-if="q.trim()" class="result-summary">
        找到 {{ videoResults.length }} 个视频、{{ comicResults.length }} 本漫画
      </p>
    </div>

    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>搜索中...</p>
    </div>

    <div v-else-if="!q.trim()" class="empty-state">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1.5">
        <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
      </svg>
      <p>输入关键词，同时搜索视频与漫画</p>
    </div>

    <div v-else-if="videoResults.length === 0 && comicResults.length === 0" class="empty-state">
      <p>没有找到与「{{ q.trim() }}」相关的内容</p>
    </div>

    <template v-else>
      <section v-if="videoResults.length > 0" class="result-section">
        <h2 class="section-title">视频（{{ videoResults.length }}）</h2>
        <div class="result-grid">
          <MediaCard
            v-for="item in videoResults"
            :key="item.type + ':' + item.hash"
            :item="item"
            data-testid="search-video"
          />
        </div>
      </section>

      <section v-if="comicResults.length > 0" class="result-section">
        <h2 class="section-title">漫画（{{ comicResults.length }}）</h2>
        <div class="result-grid">
          <MediaCard
            v-for="item in comicResults"
            :key="item.type + ':' + item.hash"
            :item="item"
            data-testid="search-comic"
          />
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.search-page { padding: 24px; max-width: 1400px; margin: 0 auto; min-height: 100vh; background: #0f0f0f; color: #fff; }
.search-header { margin-bottom: 24px; }
.search-box { position: relative; max-width: 600px; }
.search-icon { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); color: #666; }
.search-input { width: 100%; height: 48px; padding: 0 16px 0 48px; border: 1px solid #333; border-radius: 12px; background: #1a1a1a; color: #fff; font-size: 15px; }
.search-input:focus { outline: none; border-color: #2196F3; box-shadow: 0 0 0 3px rgba(33,150,243,0.1); }
.result-summary { margin: 12px 0 0; color: #888; font-size: 14px; }
.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 300px; }
.spinner { width: 48px; height: 48px; border: 3px solid #333; border-top-color: #2196F3; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 360px; color: #666; }
.empty-state p { font-size: 16px; }
.result-section { margin-bottom: 32px; }
.section-title { font-size: 20px; font-weight: 600; color: #fff; margin: 0 0 16px; }
.result-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
@media (max-width: 768px) {
  .search-page { padding: 16px; }
  .result-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
}
</style>
