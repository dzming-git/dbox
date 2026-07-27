<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { textApi } from '../api'
import { useWatchLaterStore } from '../stores/watchLaterStore'
import type { TextResource } from '../types'

const route = useRoute()
const router = useRouter()
const watchLaterStore = useWatchLaterStore()

const text = ref<TextResource | null>(null)
const loading = ref(true)
const error = ref('')

const isWatchLater = computed(() => !!text.value && watchLaterStore.has('text', String(text.value.id)))
const toggleWatchLater = () => {
  if (!text.value) return
  const id = String(text.value.id)
  watchLaterStore.toggle({ type: 'text', id, title: title() })
}

const title = () => text.value?.presentation?.title || `文本 ${text.value?.id ?? ''}`

onMounted(async () => {
  loading.value = true
  error.value = ''
  try {
    const id = Number(route.params.id)
    const res = await textApi.get(id)
    text.value = res
  } catch (e: any) {
    error.value = e?.response?.data?.message || '加载失败'
  } finally {
    loading.value = false
  }
})

const goBack = () => {
  if (window.history.length > 1) router.back()
  else router.push('/?mode=text')
}
</script>

<template>
  <div class="detail-page text-detail">
    <header class="detail-bar">
      <button class="back-btn" @click="goBack">← 返回</button>
      <h1 class="detail-title">{{ title() }}</h1>
      <button class="watchlater-detail-btn" :class="{ active: isWatchLater }" @click="toggleWatchLater">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
        <span>{{ isWatchLater ? '已加入稍后再看' : '稍后再看' }}</span>
      </button>
    </header>

    <div v-if="loading" class="detail-loading">加载中…</div>
    <div v-else-if="error" class="detail-error">{{ error }}</div>
    <div v-else-if="text" class="detail-body">
      <p v-if="text.summary" class="text-summary">{{ text.summary }}</p>
      <article class="text-content">{{ text.body }}</article>
    </div>
  </div>
</template>

<style scoped>
.text-detail { padding: 12px 16px 32px; max-width: 920px; margin: 0 auto; }
.detail-bar {
  display: flex; align-items: center; gap: 12px;
  position: sticky; top: 0; background: var(--bg, #fff);
  padding: 10px 0; z-index: 5; border-bottom: 1px solid var(--border, #eee);
}
.back-btn {
  border: none; background: transparent; color: var(--accent, #39f);
  font-size: 15px; cursor: pointer; padding: 4px 6px;
}
.detail-title { font-size: 20px; margin: 0; flex: 1; }
.watchlater-detail-btn {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border, #ddd); background: var(--bg-elev, #f6f6f8);
  color: #666; border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 14px;
  white-space: nowrap;
}
.watchlater-detail-btn:hover { color: #333; }
.watchlater-detail-btn.active { color: #ff9f00; border-color: rgba(255,159,0,0.5); background: rgba(255,159,0,0.1); }
.detail-loading, .detail-error { padding: 32px; text-align: center; color: #888; }
.text-summary { color: #666; font-size: 14px; background: #f6f6f8; padding: 10px 14px; border-radius: 8px; }
.text-content {
  margin-top: 16px; white-space: pre-wrap; word-break: break-word;
  line-height: 1.8; font-size: 15px; color: #222;
}
</style>
