<template>
  <div class="subs-page">
    <h2 class="subs-title">订阅管理</h2>

    <div class="subs-tabs">
      <button class="subs-tab" :class="{ active: tab === 'manage' }" @click="tab = 'manage'">订阅来源</button>
      <button class="subs-tab" :class="{ active: tab === 'cache' }" @click="tab = 'cache'">订阅动态</button>
    </div>

    <!-- 订阅来源：配置哪些 handle 要盯 -->
    <div v-if="tab === 'manage'">
      <p class="subs-hint">
        订阅你关注的来源（X 账号 / pixiv 画师等）。对应扩展会在拉取到新内容后，
        先缓存到下方「订阅动态」，是否下载入库由你决定。
      </p>

      <div class="subs-add">
        <select v-model="form.sourceType" class="subs-input">
          <option value="x">X（Twitter）</option>
          <option value="pixiv">pixiv</option>
        </select>
        <input v-model.trim="form.sourceId" class="subs-input" placeholder="来源 ID / handle，如 @handle 或画师 id" />
        <input v-model.trim="form.sourceName" class="subs-input" placeholder="展示名（可选）" />
        <select v-model="form.targetMode" class="subs-input">
          <option value="video">视频</option>
          <option value="comic">图集</option>
          <option value="post">帖子</option>
          <option value="text">文本</option>
        </select>
        <select v-model.number="form.libraryId" class="subs-input">
          <option :value="null">默认库</option>
          <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
        </select>
        <button class="subs-btn" :disabled="adding || !form.sourceId" @click="add">添加订阅</button>
      </div>

      <div v-if="loading" class="subs-loading">加载中…</div>
      <div v-else-if="!items.length" class="subs-empty">还没有订阅，先在上方添加一个吧。</div>
      <div v-else class="subs-list">
        <div v-for="s in items" :key="s.id" class="subs-row" :class="{ off: !s.enabled }">
          <div class="subs-main">
            <span class="subs-src" :class="`badge-${s.sourceType}`">{{ s.sourceType }}</span>
            <span class="subs-id">{{ s.sourceName || s.sourceId }}</span>
            <span v-if="s.sourceName" class="subs-handle">{{ s.sourceId }}</span>
          </div>
          <div class="subs-sub">
            <span>模式：{{ s.targetMode }}</span>
            <span v-if="s.lastItemAt">最近更新：{{ s.lastItemAt }}</span>
            <span v-if="s.error" class="subs-err">⚠ {{ s.error }}</span>
          </div>
          <div class="subs-ops">
            <label class="subs-toggle">
              <input type="checkbox" v-model="s.enabled" @change="toggleEnabled(s)" />
              启用
            </label>
            <button class="subs-del" @click="remove(s)">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 订阅动态：轮询到的缓存内容，是否入库用户说了算 -->
    <div v-else>
      <p class="subs-hint">
        扩展拉取到的新内容会先缓存在这里（不自动入库）。点「入库」才触发对应扩展
        按上方配置的目标库 / 模式下载；「原帖」打开来源链接，「忽略」丢弃。
      </p>

      <label class="subs-toggle cache-toggle">
        <input type="checkbox" v-model="showIngested" @change="loadCache" />
        显示已入库
      </label>

      <div v-if="cacheLoading" class="subs-loading">加载中…</div>
      <div v-else-if="!cacheItems.length" class="subs-empty">还没有缓存内容。订阅来源后，扩展拉到新内容会出现在这里。</div>
      <div v-else class="cache-list">
        <div v-for="c in cacheItems" :key="c.id" class="cache-row" :class="{ done: c.ingested }">
          <img v-if="c.media && c.media[0] && (c.media[0].thumbnail || c.media[0].url)"
               class="cache-thumb" :src="(c.media[0].thumbnail || c.media[0].url)" alt="" loading="lazy" />
          <div class="cache-body">
            <div class="cache-head">
              <span class="subs-src" :class="`badge-${c.sourceType}`">{{ c.sourceType }}</span>
              <span class="cache-author">@{{ c.sourceId }}</span>
              <span v-if="c.ingested" class="cache-ingested">已入库</span>
            </div>
            <div class="cache-text">{{ c.text || '（无文字内容）' }}</div>
            <div class="cache-meta">
              <span>目标：{{ c.targetMode }}{{ c.libraryId ? ' / 库#' + c.libraryId : '' }}</span>
              <span v-if="c.cachedAt">缓存：{{ c.cachedAt }}</span>
            </div>
            <div class="cache-ops">
              <button class="cache-btn primary" :disabled="c.ingested" @click="ingest(c)">入库</button>
              <button class="cache-btn" v-if="c.url" @click="openExternal(c)">原帖</button>
              <button class="cache-btn danger" @click="dismiss(c)">忽略</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { subscriptionApi, type SubscriptionInput, type SubscriptionCache } from '../api'
import { libraryApi } from '../api'
import { useToast } from '../composables/useToast'

const { showToast } = useToast()
const route = useRoute()

const tab = ref<'manage' | 'cache'>('manage')
const items = ref<Subscription[]>([])
const libraries = ref<{ id: number; name: string }[]>([])
const loading = ref(false)
const adding = ref(false)

const cacheItems = ref<SubscriptionCache[]>([])
const cacheLoading = ref(false)
const showIngested = ref(false)

const form = reactive<SubscriptionInput>({
  sourceType: 'x',
  sourceId: '',
  sourceName: '',
  targetMode: 'video',
  libraryId: null,
  enabled: true,
})

onMounted(() => {
  // 通知点击「订阅动态」时带 ?tab=cache 跳转进来
  if (route.query.tab === 'cache') tab.value = 'cache'
  load()
  loadLibraries()
  loadCache()
})

async function load() {
  loading.value = true
  try {
    const res: any = await subscriptionApi.list()
    items.value = (res && res.success && Array.isArray(res.items)) ? res.items : []
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

async function loadLibraries() {
  try {
    const res: any = await libraryApi.getUserLibraries()
    const libs = res && res.success && Array.isArray(res.libraries) ? res.libraries : []
    libraries.value = libs.map((l: any) => ({ id: l.id, name: l.name }))
  } catch {
    libraries.value = []
  }
}

async function loadCache() {
  cacheLoading.value = true
  try {
    const params: any = {}
    if (!showIngested.value) params.ingested = '0'
    const res: any = await subscriptionApi.cacheList(params)
    cacheItems.value = (res && res.success && Array.isArray(res.items)) ? res.items : []
  } catch {
    cacheItems.value = []
  } finally {
    cacheLoading.value = false
  }
}

async function add() {
  if (!form.sourceId) return
  adding.value = true
  try {
    const res: any = await subscriptionApi.create({
      sourceType: form.sourceType,
      sourceId: form.sourceId,
      sourceName: form.sourceName || undefined,
      targetMode: form.targetMode,
      libraryId: form.libraryId,
      enabled: form.enabled,
    })
    if (res && res.success) {
      form.sourceId = ''
      form.sourceName = ''
      await load()
    } else {
      showToast((res && res.message) || '添加失败')
    }
  } catch (e: any) {
    showToast(e?.message || '添加失败')
  } finally {
    adding.value = false
  }
}

async function toggleEnabled(s: Subscription) {
  try {
    await subscriptionApi.update(s.id, { enabled: s.enabled })
  } catch {
    s.enabled = !s.enabled
    showToast('更新失败')
  }
}

async function remove(s: Subscription) {
  try {
    await subscriptionApi.remove(s.id)
    items.value = items.value.filter((x) => x.id !== s.id)
  } catch {
    showToast('删除失败')
  }
}

// 入库：先经扩展代理触发下载，再标记已入库
async function ingest(c: SubscriptionCache) {
  if (c.ingested) return
  try {
    await subscriptionApi.runDownload(c.sourceType, {
      library_id: c.libraryId,
      params: {
        url: c.url,
        title: (c.text || '').slice(0, 80),
        target_modes: [c.targetMode],
      },
    })
  } catch (e: any) {
    showToast('触发下载失败：' + (e?.message || e))
  }
  try {
    await subscriptionApi.cacheIngest(c.id)
  } catch {
    // 下载已触发，标记失败不影响下载
  }
  showToast('已提交入库下载任务')
  await loadCache()
}

function openExternal(c: SubscriptionCache) {
  if (c.url) window.open(c.url, '_blank', 'noopener')
}

async function dismiss(c: SubscriptionCache) {
  try {
    await subscriptionApi.cacheDismiss(c.id)
    cacheItems.value = cacheItems.value.filter((x) => x.id !== c.id)
  } catch {
    showToast('忽略失败')
  }
}
</script>

<style scoped>
.subs-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 16px;
}
.subs-title {
  font-size: 22px;
  margin: 0 0 6px;
}
.subs-hint {
  color: var(--text-muted, #9ca3af);
  margin: 0 0 18px;
  font-size: 14px;
}
.subs-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--border, #2a2a2a);
}
.subs-tab {
  background: none;
  border: none;
  color: var(--text-muted, #9ca3af);
  padding: 8px 14px;
  cursor: pointer;
  font-size: 15px;
  border-bottom: 2px solid transparent;
}
.subs-tab.active {
  color: var(--text, #eee);
  border-bottom-color: var(--accent, #f97316);
}
.subs-add {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}
.subs-input {
  background: var(--input-bg, #1f2937);
  border: 1px solid var(--border, #333);
  color: var(--text, #eee);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 14px;
}
.subs-btn {
  background: var(--accent, #f97316);
  border: none;
  color: #fff;
  border-radius: 8px;
  padding: 8px 16px;
  cursor: pointer;
}
.subs-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}
.subs-loading,
.subs-empty {
  color: var(--text-muted, #9ca3af);
  padding: 20px 0;
}
.subs-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.subs-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border, #2a2a2a);
  border-radius: 10px;
}
.subs-row.off {
  opacity: .55;
}
.subs-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
}
.subs-src {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(249, 115, 22, .15);
  color: var(--accent, #f97316);
}
.subs-id {
  font-weight: 600;
}
.subs-handle {
  color: var(--text-muted, #6b7280);
  font-size: 12px;
}
.subs-sub {
  display: flex;
  gap: 12px;
  flex: 1;
  flex-wrap: wrap;
  color: var(--text-muted, #9ca3af);
  font-size: 12px;
}
.subs-err {
  color: var(--danger, #ef4444);
}
.subs-ops {
  display: flex;
  align-items: center;
  gap: 12px;
}
.subs-toggle {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.cache-toggle {
  margin-bottom: 14px;
}
.subs-del {
  background: none;
  border: 1px solid var(--border, #444);
  color: var(--text-muted, #9ca3af);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
}
.subs-del:hover {
  color: var(--danger, #ef4444);
  border-color: var(--danger, #ef4444);
}
.cache-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.cache-row {
  display: flex;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border, #2a2a2a);
  border-radius: 10px;
}
.cache-row.done {
  opacity: .6;
}
.cache-thumb {
  width: 84px;
  height: 84px;
  object-fit: cover;
  border-radius: 8px;
  flex: 0 0 auto;
  background: #111;
}
.cache-body {
  flex: 1;
  min-width: 0;
}
.cache-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cache-author {
  font-weight: 600;
}
.cache-ingested {
  font-size: 11px;
  color: var(--like, #f97316);
  border: 1px solid var(--like, #f97316);
  border-radius: 6px;
  padding: 1px 6px;
}
.cache-text {
  margin-top: 6px;
  font-size: 14px;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.cache-meta {
  margin-top: 6px;
  display: flex;
  gap: 12px;
  color: var(--text-muted, #6b7280);
  font-size: 12px;
}
.cache-ops {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.cache-btn {
  background: var(--input-bg, #1f2937);
  border: 1px solid var(--border, #444);
  color: var(--text, #eee);
  border-radius: 6px;
  padding: 5px 12px;
  font-size: 13px;
  cursor: pointer;
}
.cache-btn.primary {
  background: var(--accent, #f97316);
  border-color: var(--accent, #f97316);
  color: #fff;
}
.cache-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}
.cache-btn.danger:hover {
  color: var(--danger, #ef4444);
  border-color: var(--danger, #ef4444);
}
</style>
