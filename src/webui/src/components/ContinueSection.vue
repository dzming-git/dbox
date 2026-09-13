<script setup lang="ts">
import { ref, onMounted, onActivated } from 'vue'
import { useRouter } from 'vue-router'
import { fetchHistory, type MediaItem } from '../utils/media'

/**
 * 「继续」聚合入口：跨模态（视频 / 图集）把「看了但没看完」的内容按最近时间聚到一处，
 * 让用户回到首页一次点击就能接着上次继续，而不必分别去历史、稍后再看、收藏里找。
 * 数据源复用后端 /api/history（唯一数据源，跨设备一致），本组件只做筛选与排序，不新增后端接口。
 */
const router = useRouter()
const items = ref<MediaItem[]>([])
const loading = ref(false)

// 只看「进行中」：刚点开(<2%)和已看完(>=98%)都不属于"要继续的"，否则一进首页就是满屏看完的东西
const MIN_P = 0.02
const MAX_P = 0.98
const MAX_SHOW = 8

const load = async () => {
  loading.value = true
  try {
    const all = await fetchHistory()
    items.value = (all || [])
      .filter((it) => (it.progress || 0) > MIN_P && (it.progress || 0) < MAX_P)
      .sort((a, b) => String(b.date || '').localeCompare(String(a.date || '')))
      .slice(0, MAX_SHOW)
  } catch (e) {
    console.error('加载「继续」失败:', e)
    items.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)
onActivated(load)   // 从详情页返回首页时刷新进度

const open = (it: MediaItem) => {
  if (it.type === 'video') {
    // 与 History 的「继续」完全一致：带 t=秒 直达上次位置
    const seconds = Math.floor((it.progress || 0) * (it.duration || 0))
    router.push({ path: `/video/${it.hash}`, query: { t: seconds } })
  } else {
    router.push(`/gallery/${it.hash}`)
  }
}
const pct = (p?: number) => Math.max(0, Math.min(100, Math.round((p || 0) * 100)))
const remainText = (it: MediaItem) => {
  if (it.type === 'video' && it.duration) {
    const left = Math.max(0, Math.round(it.duration * (1 - (it.progress || 0))))
    return left >= 60 ? `还剩 ${Math.floor(left / 60)} 分钟` : `还剩 ${left} 秒`
  }
  if (it.type === 'gallery') {
    return it.pageCount ? `第 ${it.page || 1} / ${it.pageCount} 页` : `第 ${it.page || 1} 页`
  }
  return ''
}
</script>

<template>
  <section v-if="items.length" class="cs">
    <div class="cs-head">
      <h2 class="cs-title">继续</h2>
      <span class="cs-sub">接着上次看</span>
    </div>
    <div class="cs-list">
      <button
        v-for="it in items"
        :key="it.type + it.hash"
        class="cs-card"
        :title="it.title"
        @click="open(it)"
      >
        <img class="cs-cover" :src="it.cover" :alt="it.title" loading="lazy" decoding="async" />
        <div class="cs-bar"><i :style="{ width: pct(it.progress) + '%' }"></i></div>
        <div class="cs-meta">
          <span class="cs-name">{{ it.title }}</span>
          <span class="cs-left">{{ remainText(it) }}</span>
        </div>
      </button>
    </div>
  </section>
</template>

<style scoped>
.cs { margin: var(--space-4, 16px) 0 var(--space-3, 12px); }
.cs-head { display: flex; align-items: baseline; gap: var(--space-2, 8px); margin-bottom: var(--space-2, 8px); }
.cs-title { margin: 0; font-size: 16px; font-weight: 600; color: var(--text-primary); }
.cs-sub { font-size: 12px; color: var(--text-tertiary); }
.cs-list {
  display: grid; gap: var(--space-3, 12px);
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
}
.cs-card {
  padding: 0; border: 1px solid var(--border-default); border-radius: var(--radius-md, 10px);
  background: var(--bg-surface); overflow: hidden; cursor: pointer; text-align: left;
  transition: border-color var(--transition-fast, .15s ease), background var(--transition-fast, .15s ease);
}
.cs-card:hover { border-color: var(--accent-border); background: var(--bg-surface-hover); }
.cs-cover { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: var(--bg-surface-2); }
.cs-bar { height: 3px; background: var(--bg-surface-2); }
.cs-bar i { display: block; height: 100%; background: var(--accent); }
.cs-meta { display: flex; flex-direction: column; gap: 2px; padding: var(--space-2, 8px); }
.cs-name {
  font-size: 13px; color: var(--text-primary); line-height: 1.4;
  overflow: hidden; text-overflow: ellipsis; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
}
.cs-left { font-size: 11px; color: var(--text-tertiary); }
</style>
