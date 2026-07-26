<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { textApi } from '../api'
import type { TextResource } from '../types'

const route = useRoute()
const router = useRouter()

const text = ref<TextResource | null>(null)
const loading = ref(true)
const error = ref('')

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
.detail-loading, .detail-error { padding: 32px; text-align: center; color: #888; }
.text-summary { color: #666; font-size: 14px; background: #f6f6f8; padding: 10px 14px; border-radius: 8px; }
.text-content {
  margin-top: 16px; white-space: pre-wrap; word-break: break-word;
  line-height: 1.8; font-size: 15px; color: #222;
}
</style>
