<script setup lang="ts">
defineOptions({ name: 'Search' })
import { ref, onMounted, watch, computed, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import { videoApi, galleryApi, postApi, textApi, userStateApi } from '../api'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import type { MediaItem } from '../utils/media'
import MediaCard from '../components/MediaCard.vue'

const route = useRoute()
const q = ref((route.query.q as string) || '')
const videoResults = ref<MediaItem[]>([])
const galleryResults = ref<MediaItem[]>([])
const postResults = ref<MediaItem[]>([])
const textResults = ref<MediaItem[]>([])
const loading = ref(false)

type Tab = 'all' | 'video' | 'gallery' | 'post' | 'text'
const activeTab = ref<Tab>('all')
const tabs: { key: Tab; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'video', label: '视频' },
  { key: 'gallery', label: '图集' },
  { key: 'post', label: '帖子' },
  { key: 'text', label: '文本' },
]

// 搜索历史：存于跨设备用户状态，与「保存的视图」同一套机制
const history = ref<string[]>([])
async function loadHistory() {
  try {
    const res: any = await userStateApi.get('core', 'search-history')
    const v = res?.value
    history.value = Array.isArray(v) ? v.filter((x: any) => typeof x === 'string').slice(0, 10) : []
  } catch {
    history.value = []
  }
}
async function rememberHistory(text: string) {
  const t = (text || '').trim()
  if (!t) return
  const next = [t, ...history.value.filter((x) => x !== t)].slice(0, 10)
  history.value = next
  try {
    await userStateApi.put('core', 'search-history', next, { strategy: 'lww', scope: 'user' })
  } catch {
    /* 历史丢失不影响搜索本身 */
  }
}
function clearHistory() {
  history.value = []
  userStateApi.put('core', 'search-history', [], { strategy: 'lww', scope: 'user' }).catch(() => {})
}

const search = async () => {
  const query = q.value.trim()
  if (!query) {
    videoResults.value = []
    galleryResults.value = []
    postResults.value = []
    textResults.value = []
    return
  }
  loading.value = true
  try {
    // type:xxx 时只查对应类型：其余接口不认这套语法（会把整串当标题搜），
    // 一起并发等于给每个类型都发了一次「必然为空」的请求。
    const kind = (query.match(/(?:type|kind):(\S+)/i) || [])[1]?.toLowerCase() || ''
    const want = (k: string) => !kind || kind.startsWith(k)
    const [v, c, p, t] = await Promise.all([
      want('video') ? (videoApi.getVideos({ search: query, limit: 60 }) as any) : Promise.resolve(null),
      want('gallery') ? (galleryApi.getGallerys({ search: query, limit: 60 }) as any) : Promise.resolve(null),
      want('post') ? (postApi.list({ search: query }) as any) : Promise.resolve(null),
      want('text') ? (textApi.list({ search: query }) as any) : Promise.resolve(null),
    ])
    videoResults.value = (v?.videos || []).map((x: any) => ({
      type: 'video', hash: x.hash, title: x.title,
      cover: x.thumbnail || '', thumbnail: x.thumbnail, duration: x.duration, raw: x
    }))
    galleryResults.value = (c?.galleries || []).map((x: any) => ({
      type: 'gallery', hash: x.hash, title: x.title,
      cover: x.cover_url || '', pageCount: x.page_count, raw: x
    }))
    postResults.value = (p?.posts || []).map((x: any) => ({
      type: 'post', hash: String(x.id), title: x.title,
      cover: x.cover_url || '', raw: x
    }))
    textResults.value = (t?.texts || []).map((x: any) => ({
      type: 'text', hash: String(x.id), title: x.title || x.body?.slice(0, 20) || '文本',
      cover: x.cover || '', raw: x
    }))
    await rememberHistory(query)
  } catch (e) {
    console.error('搜索失败:', e)
  } finally {
    loading.value = false
  }
}

const totalCount = computed(
  () => videoResults.value.length + galleryResults.value.length + postResults.value.length + textResults.value.length
)

const tabLabel = computed(() => tabs.find((t) => t.key === activeTab.value)?.label || '')

const visibleResults = computed<MediaItem[]>(() => {
  switch (activeTab.value) {
    case 'video': return videoResults.value
    case 'gallery': return galleryResults.value
    case 'post': return postResults.value
    case 'text': return textResults.value
    default: return [
      ...videoResults.value,
      ...galleryResults.value,
      ...postResults.value,
      ...textResults.value,
    ]
  }
})

const countOf = (key: Tab) => {
  switch (key) {
    case 'video': return videoResults.value.length
    case 'gallery': return galleryResults.value.length
    case 'post': return postResults.value.length
    case 'text': return textResults.value.length
    default: return totalCount.value
  }
}

let timer: number | null = null
watch(q, () => {
  if (timer) clearTimeout(timer)
  timer = window.setTimeout(search, 400)
})
watch(activeTab, () => {})

onMounted(() => {
  loadHistory()
  search()
})

// 语法提示：把可写的条件摆出来，否则没人知道搜索框支持什么
const SYNTAX_HINTS = [
  { code: 'tag:名称', desc: '带某个标签' },
  { code: 'library:名称', desc: '属于某资源库' },
  { code: 'type:video', desc: '限定类型' },
  { code: 'date:2026-09', desc: '某段时间加入' },
  { code: 'duration:>20min', desc: '时长条件' },
]
function applyHint(code: string) {
  const cur = q.value.trim()
  q.value = cur ? `${cur} ${code}` : code
}

// 顶部下拉刷新：按当前关键词重新搜索
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(search)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())
</script>

<template>
  <div class="search-page">
    <div class="search-header">
      <div class="search-box">
        <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
        </svg>
        <input v-model="q" type="text" placeholder="搜索视频、图集、帖子、文本..." class="search-input" autofocus />
      </div>
      <p v-if="q.trim()" class="result-summary">
        找到 {{ totalCount }} 条结果
      </p>
    </div>

    <!-- 语法提示与搜索历史：只在还没输入时出现，避免干扰结果 -->
    <div v-if="!q.trim()" class="search-assist">
      <div class="assist-block">
        <div class="assist-title">可以直接写条件</div>
        <div class="hint-chips">
          <button
            v-for="h in SYNTAX_HINTS"
            :key="h.code"
            class="hint-chip"
            :title="h.desc"
            @click="applyHint(h.code)"
          >{{ h.code }}</button>
        </div>
      </div>
      <div v-if="history.length" class="assist-block">
        <div class="assist-title">
          最近搜索
          <button class="assist-clear" @click="clearHistory">清空</button>
        </div>
        <div class="hint-chips">
          <button
            v-for="h in history"
            :key="h"
            class="hint-chip history-chip"
            @click="q = h"
          >{{ h }}</button>
        </div>
      </div>
    </div>

    <div class="search-tabs" v-if="q.trim() && totalCount > 0">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="search-tab"
        :class="{ active: activeTab === tab.key }"
        @click="activeTab = tab.key"
      >
        {{ tab.label }}<span class="tab-count" v-if="countOf(tab.key)">{{ countOf(tab.key) }}</span>
      </button>
    </div>

    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>搜索中...</p>
    </div>

    <div v-else-if="!q.trim()" class="empty-state">
      <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1.5">
        <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
      </svg>
      <p>输入关键词，跨视频 / 图集 / 帖子 / 文本 同时搜索</p>
    </div>

    <div v-else-if="totalCount === 0" class="empty-state">
      <p>没有找到与「{{ q.trim() }}」相关的内容</p>
    </div>

    <div v-else-if="visibleResults.length === 0" class="empty-state">
      <p>「{{ tabLabel }}」分类下没有结果</p>
    </div>

    <div v-else class="result-grid">
      <MediaCard
        v-for="item in visibleResults"
        :key="item.type + ':' + item.hash"
        :item="item"
        :data-testid="`search-${item.type}`"
      />
    </div>
  </div>
</template>

<style scoped>
.search-page { padding: 24px; max-width: 1400px; margin: 0 auto; min-height: 100vh; background: var(--bg-surface); color: var(--text-primary); }
.search-header { margin-bottom: 20px; }
.search-box { position: relative; max-width: 600px; }
.search-icon { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); color: var(--text-tertiary); }
.search-input { width: 100%; height: 48px; padding: 0 16px 0 48px; border: 1px solid var(--border-default); border-radius: 12px; background: var(--bg-surface); color: var(--text-primary); font-size: 15px; }
.search-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px rgba(33,150,243,0.1); }
.result-summary { margin: 12px 0 0; color: var(--text-secondary); font-size: 14px; }
.search-assist { margin: 18px 0 4px; display: flex; flex-direction: column; gap: 14px; }
.assist-block { max-width: 680px; }
.assist-title { font-size: 12px; color: var(--text-tertiary); margin-bottom: 8px; display: flex; align-items: center; gap: 10px; }
.assist-clear { background: transparent; border: none; color: var(--text-tertiary); font-size: 12px; cursor: pointer; }
.assist-clear:hover { color: var(--accent); }
.hint-chips { display: flex; gap: 8px; flex-wrap: wrap; }
.hint-chip {
  background: var(--bg-surface);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.18s ease, border-color 0.18s ease;
}
.hint-chip:hover { color: var(--accent); border-color: var(--accent-border); }
.history-chip { font-family: inherit; }
.search-tabs { display: flex; gap: 8px; margin-bottom: 20px; flex-wrap: wrap; }
.search-tab {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: 999px;
  background: var(--bg-surface); color: var(--text-secondary); border: 1px solid var(--border-default);
  font-size: 14px; cursor: pointer; transition: all 0.2s;
}
.search-tab:hover { background: var(--bg-surface-hover); }
.search-tab.active { background: var(--accent); color: var(--text-on-accent); border-color: var(--accent); }
.tab-count { font-size: 12px; opacity: 0.8; }
.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 300px; }
.spinner { width: 48px; height: 48px; border: 3px solid var(--border-default); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 360px; color: var(--text-tertiary); }
.empty-state p { font-size: 16px; }
.result-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 20px; }
@media (max-width: 768px) {
  .search-page { padding: 16px; }
  .result-grid { grid-template-columns: repeat(2, 1fr); gap: 12px; }
}
</style>
