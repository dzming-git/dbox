<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { textApi } from '../api'
import { useWatchLaterStore } from '../stores/watchLaterStore'
import { useUserStore } from '../stores/userStore'
import type { TextResource } from '../types'

const route = useRoute()
const router = useRouter()
const watchLaterStore = useWatchLaterStore()
const userStore = useUserStore()

const text = ref<TextResource | null>(null)
const loading = ref(true)
const error = ref('')

const isWatchLater = computed(() => !!text.value && watchLaterStore.has('text', String(text.value.id)))
const toggleWatchLater = () => {
  if (!text.value) return
  const id = String(text.value.id)
  watchLaterStore.toggle({ type: 'text', id, title: title() })
}

// 删除（仅管理员，列表/卡片已不再提供删除入口）
const canManage = computed(() => !!userStore.user && userStore.user.role <= UserRole.ADMIN)
const removeText = async () => {
  if (!text.value) return
  if (!confirm('确定删除该文本？此操作不可恢复。')) return
  try {
    await textApi.remove(text.value.id)
    router.push('/?mode=text')
  } catch (e: any) {
    alert(e?.message || '删除失败')
  }
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
      <button v-if="canManage" class="delete-detail-btn" @click="removeText" title="删除文本">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
        <span>删除</span>
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
  position: sticky; top: 0; background: var(--bg-base);
  padding: 10px 0; z-index: 5; border-bottom: 1px solid var(--border-default);
  color: var(--text-primary);
}
.back-btn {
  border: none; background: transparent; color: var(--accent, #39f);
  font-size: 15px; cursor: pointer; padding: 4px 6px;
}
.detail-title { font-size: 20px; margin: 0; flex: 1; }
.watchlater-detail-btn {
  display: inline-flex; align-items: center; gap: 6px;
  border: 1px solid var(--border, var(--text-secondary)); background: var(--bg-elev, #f6f6f8);
  color: var(--text-tertiary); border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 14px;
  white-space: nowrap;
}
.watchlater-detail-btn:hover { color: var(--accent); }
.watchlater-detail-btn.active { color: #ff9f00; border-color: rgba(255,159,0,0.5); background: rgba(255,159,0,0.1); }
.delete-detail-btn { display: inline-flex; align-items: center; gap: 6px; border: 1px solid #e0b4b4; background: #fff0f0; color: #d33; border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 14px; white-space: nowrap; }
.delete-detail-btn:hover { background: #ffe0e0; color: #b22; }
.detail-loading, .detail-error { padding: 32px; text-align: center; color: var(--text-secondary); }
.text-summary { color: var(--text-tertiary); font-size: 14px; background: #f6f6f8; padding: 10px 14px; border-radius: 8px; }
.text-content {
  margin-top: 16px; white-space: pre-wrap; word-break: break-word;
  line-height: 1.8; font-size: 15px; color: var(--text-primary);
}
</style>
