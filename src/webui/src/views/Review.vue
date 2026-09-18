<template>
  <div class="review-page">
    <div class="page-header">
      <div>
        <h2>整理审阅</h2>
        <p class="page-desc">
          把可疑条目按问题类型聚成清单，照着处理即可。这里只做检测与处置，
          <b>不会自动删除任何东西</b>。
        </p>
      </div>
      <button class="refresh-btn" @click="loadAll" :disabled="loading">刷新</button>
    </div>

    <!-- 概览：先看清楚每一类各有多少，再决定先处理哪一类 -->
    <div v-if="summary" class="kind-grid">
      <button
        v-for="k in KINDS"
        :key="k.value"
        class="kind-card"
        :class="{ active: currentKind === k.value, empty: !countOf(k.value) }"
        @click="selectKind(k.value)"
      >
        <span class="kind-name">{{ k.label }}</span>
        <span class="kind-count">{{ countOf(k.value) }}<i v-if="moreOf(k.value)">+</i></span>
        <span class="kind-hint">{{ k.hint }}</span>
      </button>
    </div>

    <!-- 本类专属的批量动作 -->
    <div v-if="currentKind" class="toolbar">
      <span class="toolbar-label">{{ kindLabel(currentKind) }}（{{ items.length }}）</span>

      <template v-if="currentKind === 'no_metadata'">
        <button class="action-btn primary" :disabled="busy" @click="runBackfill">
          补齐时长与大小
        </button>
        <span class="toolbar-tip">走后台任务，可在任务中心看进度或停止</span>
      </template>

      <template v-else>
        <span class="toolbar-tip" v-if="!selectedIds.length">勾选条目后可批量处置</span>
        <template v-if="selectedIds.length">
          <span class="selected-count">已选 {{ selectedIds.length }}</span>
          <button class="action-btn danger" :disabled="busy" @click="doTrash">
            移入回收站
          </button>
          <button class="action-btn" :disabled="busy" @click="askTag">批量打标签</button>
          <button
            v-if="currentKind === 'missing_file'"
            class="action-btn"
            :disabled="busy"
            @click="askRemap"
          >重新指向文件</button>
        </template>
      </template>

      <label class="select-all">
        <input type="checkbox" :checked="allSelected" @change="toggleAll" />
        全选本页
      </label>
    </div>

    <div v-if="loading && !items.length" class="empty-tip">加载中…</div>
    <div v-else-if="!items.length" class="empty-tip">
      这一类没有问题条目 🎉
    </div>

    <div v-else class="item-list">
      <div v-for="it in items" :key="it.id" class="item-card">
        <label class="item-check">
          <input type="checkbox" :checked="isSelected(it.id)" @change="toggle(it.id)" />
        </label>
        <div class="item-main">
          <div class="item-title" :title="it.path || ''">{{ it.title || '(无标题)' }}</div>
          <div class="item-meta">
            <span class="reason">{{ it.reason }}</span>
            <span v-if="it.duration">· {{ formatDuration(it.duration) }}</span>
            <span v-if="it.file_size">· {{ formatSize(it.file_size) }}</span>
          </div>
          <div v-if="it.path" class="item-path">{{ it.path }}</div>
        </div>
        <div class="item-actions">
          <RouterLink
            v-if="it.hash"
            :to="`/video/${it.hash}`"
            class="item-link"
            title="打开详情确认后再决定"
          >查看</RouterLink>
        </div>
      </div>
    </div>

    <div v-if="hasMore" class="pager">
      <button class="pager-btn" :disabled="loading" @click="loadMore">加载更多</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { reviewApi, type ReviewKind, type ReviewItem } from '../api/review'
import { useToast } from '../composables/useToast'
import { formatDuration } from '../utils/format'

const { showToast } = useToast()

const KINDS: { value: ReviewKind; label: string; hint: string }[] = [
  { value: 'missing_file', label: '文件已丢失', hint: '记录还在，但磁盘上已经没有文件' },
  { value: 'no_metadata', label: '缺少时长/大小', hint: '时长显示为 0，按长度筛选会失效' },
  { value: 'no_cover', label: '没有封面', hint: '列表里是空白卡片' },
  { value: 'untagged', label: '没有标签', hint: '难以被检索到' },
  { value: 'duplicate', label: '内容重复', hint: '同一份内容被登记了多次' },
]

const PAGE_SIZE = 50

const summary = ref<any>(null)
const items = ref<ReviewItem[]>([])
const currentKind = ref<ReviewKind>('missing_file')
const selected = ref<Set<number>>(new Set())
const loading = ref(false)
const busy = ref(false)
const hasMore = ref(false)

function kindLabel(v: ReviewKind) {
  return KINDS.find((k) => k.value === v)?.label || v
}
function countOf(k: ReviewKind) {
  return Number(summary.value?.[k] ?? 0)
}
function moreOf(k: ReviewKind) {
  // 概览每类最多扫 500 条，带 + 表示还有更多没统计
  return !!summary.value?.[`${k}_more`]
}

const allSelected = computed(
  () => items.value.length > 0 && items.value.every((i) => selected.value.has(i.id))
)
const selectedIds = computed(() => Array.from(selected.value))

function isSelected(id: number) {
  return selected.value.has(id)
}
function toggle(id: number) {
  const s = new Set(selected.value)
  s.has(id) ? s.delete(id) : s.add(id)
  selected.value = s
}
function toggleAll() {
  selected.value = allSelected.value
    ? new Set<number>()
    : new Set(items.value.map((i) => i.id))
}

async function loadSummary() {
  try {
    const res: any = await reviewApi.summary()
    summary.value = res?.success ? res : null
  } catch (e) {
    summary.value = null
  }
}

async function loadItems(reset = true) {
  if (reset) {
    loading.value = true
    items.value = []
    selected.value = new Set()
  }
  try {
    const res: any = await reviewApi.items(
      currentKind.value,
      PAGE_SIZE,
      reset ? 0 : items.value.length
    )
    const list: ReviewItem[] = res?.items || []
    items.value = reset ? list : items.value.concat(list)
    hasMore.value = !!res?.has_more
  } catch (e: any) {
    showToast(e?.response?.data?.message || '加载失败')
  } finally {
    loading.value = false
  }
}

function selectKind(k: ReviewKind) {
  if (currentKind.value === k) return
  currentKind.value = k
  loadItems(true)
}

function loadMore() {
  loadItems(false)
}

function loadAll() {
  loadSummary()
  loadItems(true)
}

async function doTrash() {
  if (!selectedIds.value.length) return
  if (!confirm(`确定把选中的 ${selectedIds.value.length} 项移入回收站吗？可在回收站恢复。`)) return
  busy.value = true
  try {
    const res: any = await reviewApi.action({ action: 'trash', ids: selectedIds.value })
    showToast(`已移入回收站 ${res?.done || 0} 项`)
    await loadAll()
  } catch (e: any) {
    showToast(e?.response?.data?.message || '操作失败')
  } finally {
    busy.value = false
  }
}

async function askTag() {
  const name = prompt('给选中条目打上标签（不存在则新建）')
  if (!name || !name.trim()) return
  busy.value = true
  try {
    const res: any = await reviewApi.action({
      action: 'tag',
      ids: selectedIds.value,
      tag: name.trim(),
    })
    showToast(`已打标签 ${res?.done || 0} 项`)
    await loadAll()
  } catch (e: any) {
    showToast(e?.response?.data?.message || '操作失败')
  } finally {
    busy.value = false
  }
}

async function askRemap() {
  // 文件换了位置：让用户给出新路径，重新指向索引（引用它的实体自动跟随）
  const picked = items.value.filter((i) => selected.value.has(i.id))
  if (picked.length !== 1) {
    showToast('重新指向需一次选一项（要为它指定新路径）')
    return
  }
  const target = picked[0]
  const newPath = prompt(`「${target.title}」的新文件路径：`, target.path || '')
  if (!newPath || !newPath.trim()) return
  busy.value = true
  try {
    const res: any = await reviewApi.action({
      action: 'remap',
      items: [{ id: target.id, path: newPath.trim() }],
    })
    if (res?.failed?.length) {
      showToast('重新指向失败：' + res.failed[0])
    } else {
      showToast('已重新指向新路径')
      await loadAll()
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || '操作失败')
  } finally {
    busy.value = false
  }
}

async function runBackfill() {
  busy.value = true
  try {
    const res: any = await reviewApi.backfill()
    showToast(res?.success ? '已启动补齐，可在任务中心查看进度' : (res?.message || '启动失败'))
  } catch (e: any) {
    showToast(e?.response?.data?.message || '启动失败')
  } finally {
    busy.value = false
  }
}

function formatSize(n: number) {
  if (n > 1024 ** 3) return `${(n / 1024 ** 3).toFixed(1)} GB`
  if (n > 1024 ** 2) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${Math.round(n / 1024)} KB`
}

onMounted(loadAll)
</script>

<style scoped>
.review-page {
  padding: 24px 32px 60px;
  max-width: 1100px;
  margin: 0 auto;
}
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.page-header h2 {
  margin: 0 0 6px;
  font-size: 20px;
  color: var(--text-primary);
}
.page-desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.refresh-btn {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  padding: 6px 14px;
  font-size: 13px;
  cursor: pointer;
}
.refresh-btn:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--border-default);
}

.kind-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}
.kind-card {
  display: flex;
  flex-direction: column;
  gap: 4px;
  text-align: left;
  background: var(--bg-surface);
  border: 1px solid var(--bg-surface-2);
  border-radius: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.18s ease, background 0.18s ease;
}
.kind-card:hover {
  border-color: var(--border-default);
}
.kind-card.active {
  border-color: var(--accent);
  background: var(--accent-soft);
}
.kind-name {
  font-size: 14px;
  color: var(--text-primary);
}
.kind-count {
  font-size: 22px;
  font-weight: 600;
  color: var(--text-primary);
}
.kind-count i {
  font-style: normal;
  font-size: 14px;
  color: var(--text-tertiary);
}
.kind-card.empty .kind-count {
  color: var(--text-tertiary);
}
.kind-hint {
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}
.toolbar-label {
  font-size: 13px;
  color: var(--text-primary);
  font-weight: 600;
}
.toolbar-tip {
  font-size: 12px;
  color: var(--text-tertiary);
}
.selected-count {
  font-size: 12px;
  color: var(--accent);
}
.action-btn {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
}
.action-btn:hover:not(:disabled) {
  color: var(--text-primary);
  border-color: var(--border-default);
}
.action-btn.primary {
  color: var(--accent);
  border-color: var(--accent);
}
.action-btn.danger {
  color: var(--danger);
  border-color: var(--danger-soft);
}
.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.select-all {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
}

.empty-tip {
  text-align: center;
  color: var(--text-secondary);
  padding: 48px 0;
}

.item-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.item-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  background: var(--bg-surface);
  border: 1px solid var(--bg-surface-2);
  border-radius: 10px;
  padding: 10px 14px;
}
.item-check {
  padding-top: 2px;
}
.item-main {
  flex: 1;
  min-width: 0;
}
.item-title {
  font-size: 14px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.item-meta {
  font-size: 12px;
  color: var(--text-secondary);
  margin-top: 3px;
}
.item-meta .reason {
  color: var(--warning);
}
.item-path {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 3px;
  word-break: break-all;
}
.item-actions {
  flex-shrink: 0;
}
.item-link {
  font-size: 12px;
  color: var(--accent);
  text-decoration: none;
}

.pager {
  display: flex;
  justify-content: center;
  margin-top: 16px;
}
.pager-btn {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  padding: 6px 18px;
  font-size: 12px;
  cursor: pointer;
}
.pager-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>
