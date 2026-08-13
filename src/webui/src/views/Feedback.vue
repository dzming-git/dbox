<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import {
  getIssues,
  getIssue,
  createIssue,
  updateIssue,
  addIssueComment,
  replyAndReopen,
  verifyClose,
  deleteIssue,
  extractMessage,
  type IssueListParams,
} from '../api/suggestion'
import type { Issue } from '../types'

const userStore = useUserStore()
const isAdmin = computed(() => userStore.isAdmin)

const route = useRoute()
const router = useRouter()

type View = 'list' | 'detail' | 'new'

const view = ref<View>('list')
const loading = ref(false)
const errorMsg = ref('')

const issues = ref<Issue[]>([])
const total = ref(0)
const openCount = ref(0)
const inProgressCount = ref(0)
const pendingCount = ref(0)
const closedCount = ref(0)
const statusFilter = ref<'all' | 'open' | 'in_progress' | 'pending' | 'closed'>('all')
const typeFilter = ref<'all' | 'bug' | 'suggestion' | 'other'>('all')
const keyword = ref('')
const page = ref(1)
const pageSize = 20

const selected = ref<Issue | null>(null)
const commentText = ref('')

const newTitle = ref('')
const newContent = ref('')
const newContact = ref('')
const newType = ref<'bug' | 'suggestion' | 'other'>('suggestion')
const submitting = ref(false)
const formMsg = ref('')

const typeMeta: Record<'bug' | 'suggestion' | 'other', { label: string; cls: string }> = {
  bug: { label: '缺陷', cls: 'type-bug' },
  suggestion: { label: '建议', cls: 'type-suggestion' },
  other: { label: '其他', cls: 'type-other' },
}

// 全部数量始终基于各状态计数之和（后端按全量统计，不随当前筛选变化），
// 而非 total（筛选后数量），避免点选某筛选导致「全部」计数错误地显示为筛选结果数。
const allCount = computed(() =>
  openCount.value + inProgressCount.value + pendingCount.value + closedCount.value
)

const tabs = computed(() => [
  { key: 'all', label: '全部', count: allCount.value },
  { key: 'open', label: '开放', count: openCount.value },
  { key: 'in_progress', label: '处理中', count: inProgressCount.value },
  { key: 'pending', label: '待验证', count: pendingCount.value },
  { key: 'closed', label: '已关闭', count: closedCount.value },
])

// 状态展示元数据：统一映射状态 -> 标签 / 圆点样式 / 徽章样式 / 图标类型
// pending 与 pending_verification 语义相同（待验证），均按待验证处理。
type StatusMeta = { label: string; dot: string; badge: string; icon: 'open' | 'in_progress' | 'pending' | 'resolved' | 'dismissed' }
function statusMeta(status: string, closedReason: string | null | undefined): StatusMeta {
  switch (status) {
    case 'open':
      return { label: '开放', dot: 'open', badge: 'open', icon: 'open' }
    case 'in_progress':
      return { label: '处理中', dot: 'in_progress', badge: 'in_progress', icon: 'in_progress' }
    case 'pending':
    case 'pending_verification':
      return { label: '待验证', dot: 'pending', badge: 'pending', icon: 'pending' }
    case 'closed':
      return closedReason === 'resolved'
        ? { label: '已解决', dot: 'resolved', badge: 'resolved', icon: 'resolved' }
        : { label: '已关闭', dot: 'dismissed', badge: 'dismissed', icon: 'dismissed' }
    default:
      return { label: '已关闭', dot: 'dismissed', badge: 'dismissed', icon: 'dismissed' }
  }
}

const typeTabs = computed(() => [
  { key: 'all', label: '全部类型', count: allCount.value },
  { key: 'bug', label: '缺陷', count: 0 },
  { key: 'suggestion', label: '建议', count: 0 },
  { key: 'other', label: '其他', count: 0 },
])

function formatDate(iso?: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

async function loadIssues(reset = true) {
  if (reset) page.value = 1
  loading.value = true
  errorMsg.value = ''
  const params: IssueListParams = {
    status: statusFilter.value,
    type: typeFilter.value === 'all' ? undefined : typeFilter.value,
    keyword: keyword.value || undefined,
    page: page.value,
    page_size: pageSize,
  }
  try {
    const res = await getIssues(params)
    if (res.success) {
      issues.value = res.issues
      total.value = res.total
      openCount.value = res.open_count
      inProgressCount.value = res.in_progress_count
      pendingCount.value = res.pending_count
      closedCount.value = res.closed_count
    } else {
      errorMsg.value = '加载失败'
    }
  } catch (e) {
    errorMsg.value = extractMessage(e, '加载失败，请重试')
  } finally {
    loading.value = false
  }
}

async function loadDetail(id: string) {
  loading.value = true
  errorMsg.value = ''
  try {
    const res = await getIssue(id)
    if (res.success) {
      selected.value = res.issue
      view.value = 'detail'
    } else {
      errorMsg.value = '加载详情失败'
    }
  } catch (e) {
    errorMsg.value = extractMessage(e, '加载详情失败')
  } finally {
    loading.value = false
  }
}

function openDetail(issue: Issue) {
  router.push({ path: `/feedback/${issue.id}` })
}

function backToList() {
  view.value = 'list'
  router.push({ path: '/feedback' })
}

// 切换状态标签：点「全部」时一并重置类型与关键词筛选，确保真正显示全部
function changeStatusFilter(key: 'all' | 'open' | 'in_progress' | 'pending' | 'closed') {
  statusFilter.value = key
  if (key === 'all') {
    typeFilter.value = 'all'
    keyword.value = ''
  }
  loadIssues(true)
}

// 切换类型筛选：点「全部类型」时一并清空状态与关键词，避免残留过滤
function changeTypeFilter(key: 'all' | 'bug' | 'suggestion' | 'other') {
  typeFilter.value = key
  if (key === 'all') {
    statusFilter.value = 'all'
    keyword.value = ''
  }
  loadIssues(true)
}

function openNew() {
  newTitle.value = ''
  newContent.value = ''
  newContact.value = ''
  newType.value = 'suggestion'
  formMsg.value = ''
  view.value = 'new'
}

async function submitNew() {
  if (!newTitle.value.trim() && !newContent.value.trim()) {
    formMsg.value = '标题与内容至少填写一项'
    return
  }
  submitting.value = true
  formMsg.value = ''
  try {
    const res = await createIssue({
      title: newTitle.value.trim(),
      content: newContent.value.trim(),
      type: newType.value,
      contact: newContact.value.trim() || undefined,
    })
    if (res.success) {
      view.value = 'list'
      changeStatusFilter('all')
    } else {
      formMsg.value = '提交失败'
    }
  } catch (e) {
    formMsg.value = extractMessage(e, '提交失败，请重试')
  } finally {
    submitting.value = false
  }
}

async function closeIssue(reason: 'resolved' | 'dismissed') {
  if (!selected.value) return
  loading.value = true
  try {
    const res = await updateIssue(selected.value.id, { status: 'closed', closed_reason: reason })
    if (res.success) selected.value = res.issue
  } catch (e) {
    errorMsg.value = extractMessage(e, '操作失败')
  } finally {
    loading.value = false
  }
}

async function reopenIssue() {
  if (!selected.value) return
  loading.value = true
  try {
    const res = await updateIssue(selected.value.id, { status: 'open', closed_reason: null })
    if (res.success) selected.value = res.issue
  } catch (e) {
    errorMsg.value = extractMessage(e, '操作失败')
  } finally {
    loading.value = false
  }
}

async function markPending() {
  if (!selected.value) return
  loading.value = true
  try {
    const res = await updateIssue(selected.value.id, { status: 'pending', closed_reason: null })
    if (res.success) selected.value = res.issue
  } catch (e) {
    errorMsg.value = extractMessage(e, '操作失败')
  } finally {
    loading.value = false
  }
}

async function removeIssue() {
  if (!selected.value) return
  if (!window.confirm('确定要删除该反馈单吗？此操作不可恢复，且会一并删除全部回复。')) return
  loading.value = true
  try {
    const res = await deleteIssue(selected.value.id)
    if (res.success) {
      await loadIssues()
      router.push({ path: '/feedback' })
    }
  } catch (e) {
    errorMsg.value = extractMessage(e, '删除失败')
  } finally {
    loading.value = false
  }
}

async function submitComment() {
  if (!selected.value) return
  if (!commentText.value.trim()) return
  loading.value = true
  try {
    const res = await addIssueComment(selected.value.id, { content: commentText.value.trim() })
    if (res.success) {
      selected.value = res.issue
      commentText.value = ''
    }
  } catch (e) {
    errorMsg.value = extractMessage(e, '评论失败')
  } finally {
    loading.value = false
  }
}

// 回复并重新打开：一次性追加管理员回复 + 置为开放，仅产生 1 个状态变更事件，
// 避免「先回复、再重开」两步操作各自触发事件、导致同一问题产生多个事件。
async function replyAndReopenIssue() {
  if (!selected.value) return
  const content = commentText.value.trim()
  if (!content) {
    errorMsg.value = '请先填写回复内容'
    return
  }
  loading.value = true
  try {
    const res = await replyAndReopen(selected.value.id, { content })
    if (res.success) {
      selected.value = res.issue
      commentText.value = ''
    }
  } catch (e) {
    errorMsg.value = extractMessage(e, '操作失败')
  } finally {
    loading.value = false
  }
}

// 验证完成并关闭：可选追加管理员回复 + 置为已关闭（已解决），仅产生 1 个状态变更事件，
// 避免「先回复、再关闭」两步操作各自触发事件。评论内容可选，未填写则只关闭。
async function verifyCloseIssue() {
  if (!selected.value) return
  loading.value = true
  try {
    const content = commentText.value.trim()
    const res = await verifyClose(selected.value.id, content ? { content } : {})
    if (res.success) {
      selected.value = res.issue
      commentText.value = ''
    }
  } catch (e) {
    errorMsg.value = extractMessage(e, '操作失败')
  } finally {
    loading.value = false
  }
}

// 管理员切换阶段：可直接把反馈置为任意状态。后端 PUT /api/suggestion/<id> 已支持
// 任意合法状态，这里仅做 UI 入口；选择后需点「确认变更」才生效，并给出操作反馈。
const STATUS_OPTIONS = [
  { value: 'open', label: '开放', status: 'open', reason: null },
  { value: 'in_progress', label: '处理中', status: 'in_progress', reason: null },
  { value: 'pending', label: '待验证', status: 'pending_verification', reason: null },
  { value: 'resolved', label: '已解决关闭', status: 'closed', reason: 'resolved' },
  { value: 'dismissed', label: '不处理关闭', status: 'closed', reason: 'dismissed' },
] as const

// 当前状态 -> 下拉选项 value，便于选中项与数据保持一致
const currentStatusValue = computed<string>(() => {
  const s = selected.value?.status
  const r = selected.value?.closed_reason
  if (s === 'closed') return r === 'resolved' ? 'resolved' : 'dismissed'
  if (s === 'in_progress') return 'in_progress'
  if (s === 'pending' || s === 'pending_verification') return 'pending'
  return 'open'
})

// 状态变更操作反馈
const statusMsg = ref('')

// 待确认的下拉选择：选择后不会立即生效，需点「确认变更」才提交，避免误操作且无反馈。
const pendingStatus = ref<string>(currentStatusValue.value)
// 反馈切换或状态变化后，把待确认项同步回当前状态
watch(currentStatusValue, (v) => { pendingStatus.value = v })
// 重新选择时清除上一次的操作反馈
watch(pendingStatus, () => {
  statusMsg.value = ''
  errorMsg.value = ''
})

async function applyStatus(value: string) {
  if (!selected.value) return
  const opt = STATUS_OPTIONS.find((o) => o.value === value)
  if (!opt) return
  // 状态与关闭原因均未变化则无事可做
  if (
    opt.status === selected.value.status &&
    (opt.reason ?? null) === (selected.value.closed_reason ?? null)
  ) {
    statusMsg.value = ''
    return
  }
  loading.value = true
  statusMsg.value = ''
  try {
    const payload: { status: string; closed_reason?: string | null } = { status: opt.status }
    if (opt.reason !== null) payload.closed_reason = opt.reason
    const res = await updateIssue(selected.value.id, payload)
    if (res.success) {
      selected.value = res.issue
      statusMsg.value = `状态已更新为「${opt.label}」`
    }
  } catch (e) {
    errorMsg.value = extractMessage(e, '状态变更失败')
  } finally {
    loading.value = false
  }
}

// 关键词输入防抖触发加载（状态/类型筛选改用显式处理函数，确保一致重置）
let keywordTimer: ReturnType<typeof setTimeout> | null = null
watch(keyword, () => {
  if (keywordTimer) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => loadIssues(true), 300)
})
onBeforeUnmount(() => {
  if (keywordTimer) clearTimeout(keywordTimer)
})

// 根据路由参数驱动详情视图（支持独立 URL 与浏览器前进/后退）
watch(
  () => route.params.id,
  (id) => {
    if (id) {
      loadDetail(String(id))
    } else {
      selected.value = null
      view.value = 'list'
      loadIssues(true)
    }
  },
  { immediate: true }
)
</script>

<template>
  <div class="fb-page">
    <header class="fb-header">
      <div class="fb-title">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 1C6.48 1 2 5.48 2 11c0 4.84 3.44 8.87 8 9.8V22l2.86-1.43c.43.07.87.13 1.14.13 5.52 0 10-4.48 10-10S17.52 1 12 1zm-1 14h-2v-2h2v2zm0-4h-2V7h2v4zm4 4h-2v-2h2v2zm0-4h-2V7h2v4z"/>
        </svg>
        <span>反馈中心</span>
        <small v-if="view === 'list'">开放 {{ openCount }} · 处理中 {{ inProgressCount }} · 待验证 {{ pendingCount }} · 已关闭 {{ closedCount }}</small>
      </div>
    </header>

    <!-- 列表视图 -->
    <section v-if="view === 'list'" class="fb-body">
      <div class="fb-toolbar">
        <div class="fb-tabs">
          <button
            v-for="t in tabs"
            :key="t.key"
            class="fb-tab"
            :class="{ active: statusFilter === t.key }"
            @click="changeStatusFilter(t.key as any)"
          >
            {{ t.label }} <span class="fb-tab-count">{{ t.count }}</span>
          </button>
        </div>
        <div class="fb-toolbar-right">
          <input v-model="keyword" class="fb-search" type="text" placeholder="搜索标题或内容..." />
          <button class="fb-new-btn" @click="openNew">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/></svg>
            新建反馈
          </button>
        </div>
      </div>

      <div class="fb-type-bar">
          <button
            v-for="t in typeTabs"
            :key="t.key"
            class="fb-type-tab"
            :class="[t.key, { active: typeFilter === t.key }]"
            @click="changeTypeFilter(t.key as any)"
          >
            {{ t.label }}
          </button>
      </div>

      <div v-if="loading" class="fb-loading">加载中...</div>
      <div v-else-if="errorMsg" class="fb-error">{{ errorMsg }}</div>
      <div v-else-if="issues.length === 0" class="fb-empty">暂无反馈</div>

      <ul v-else class="fb-list">
        <li
          v-for="it in issues"
          :key="it.id"
          class="fb-item"
          @click="openDetail(it)"
        >
          <span
            class="fb-dot"
            :class="statusMeta(it.status, it.closed_reason).dot"
          ></span>
          <div class="fb-item-main">
            <div class="fb-item-title">
              <span class="fb-type-badge" :class="typeMeta[it.type]?.cls">{{ typeMeta[it.type]?.label }}</span>
              {{ it.title }}
            </div>
            <div class="fb-item-meta">
              #{{ it.id }} · {{ it.author }} · {{ formatDate(it.created_at) }}
              <span v-if="it.comments.length" class="fb-comment-badge">{{ it.comments.length }} 条回复</span>
            </div>
          </div>
        </li>
      </ul>
    </section>

    <!-- 详情视图 -->
    <section v-else-if="view === 'detail' && selected" class="fb-body fb-detail">
      <button class="fb-back" @click="backToList">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
        返回列表
      </button>

      <div v-if="errorMsg" class="fb-error">{{ errorMsg }}</div>

      <div class="fb-detail-head">
        <h2 class="fb-detail-title">{{ selected.title }}</h2>
        <div class="fb-detail-id">#{{ selected.id }}</div>
      </div>

      <div class="fb-status-row">
        <span
          class="fb-badge"
          :class="statusMeta(selected.status, selected.closed_reason).badge"
        >
          <span class="fb-badge-ico">
            <svg v-if="statusMeta(selected.status, selected.closed_reason).icon === 'open'" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="8"/></svg>
            <svg v-else-if="statusMeta(selected.status, selected.closed_reason).icon === 'in_progress'" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 4V2A10 10 0 0 0 12 22a10 10 0 0 0 10-10h-2a8 8 0 1 1-8-8z"/></svg>
            <svg v-else-if="statusMeta(selected.status, selected.closed_reason).icon === 'pending'" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a10 10 0 100 20 10 10 0 000-20zm0 18a8 8 0 110-16 8 8 0 010 16zm1-13h-2v6l5 3 1-1.7-4-2.3z"/></svg>
            <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
          </span>
          {{ statusMeta(selected.status, selected.closed_reason).label }}
        </span>
        <span class="fb-type-badge" :class="typeMeta[selected.type]?.cls">{{ typeMeta[selected.type]?.label }}</span>
        <span class="fb-detail-meta">由 {{ selected.author }} 创建于 {{ formatDate(selected.created_at) }}</span>
      </div>

      <div class="fb-content-box">
        <p class="fb-content">{{ selected.content }}</p>
        <div v-if="isAdmin && selected.contact" class="fb-contact">
          联系方式：{{ selected.contact }}
        </div>
      </div>

      <div class="fb-comments" v-if="selected.comments.length">
        <div class="fb-comments-title">回复 ({{ selected.comments.length }})</div>
        <div v-for="(c, i) in selected.comments" :key="i" class="fb-comment">
          <div class="fb-comment-head">
            <span class="fb-comment-author">{{ c.author }}</span>
            <span class="fb-comment-time">{{ formatDate(c.created_at) }}</span>
          </div>
          <p class="fb-comment-content">{{ c.content }}</p>
        </div>
      </div>

      <!-- 管理员操作区 -->
      <div v-if="isAdmin" class="fb-admin">
        <div class="fb-admin-status">
          <span class="fb-admin-status-label">变更状态</span>
          <select
            class="fb-status-select"
            :value="pendingStatus"
            :disabled="loading"
            @change="pendingStatus = ($event.target as HTMLSelectElement).value"
          >
            <option v-for="o in STATUS_OPTIONS" :key="o.value" :value="o.value">{{ o.label }}</option>
          </select>
          <button
            class="fb-btn fb-btn-primary"
            :disabled="loading || pendingStatus === currentStatusValue"
            @click="applyStatus(pendingStatus)"
          >
            确认变更
          </button>
          <span v-if="statusMsg" class="fb-admin-status-ok">{{ statusMsg }}</span>
        </div>

        <div class="fb-admin-actions" v-if="selected.status === 'open'">
          <button class="fb-btn fb-btn-pending" :disabled="loading" @click="markPending">
            标记待验证
          </button>
          <button class="fb-btn fb-btn-resolved" :disabled="loading" @click="closeIssue('resolved')">
            以解决关闭
          </button>
          <button class="fb-btn fb-btn-dismissed" :disabled="loading" @click="closeIssue('dismissed')">
            不处理关闭
          </button>
        </div>
        <div class="fb-admin-actions" v-else-if="selected.status === 'pending' || selected.status === 'pending_verification'">
          <button class="fb-btn fb-btn-resolved" :disabled="loading" @click="verifyCloseIssue">
            验证完成关闭
          </button>
          <button class="fb-btn fb-btn-reopen" :disabled="loading" @click="reopenIssue">
            重新打开
          </button>
          <button class="fb-btn fb-btn-reopen-reply" :disabled="loading || !commentText.trim()" @click="replyAndReopenIssue">
            回复并重新打开
          </button>
        </div>
        <div class="fb-admin-actions" v-else-if="selected.status === 'in_progress'">
          <button class="fb-btn fb-btn-pending" :disabled="loading" @click="markPending">
            标记待验证
          </button>
          <button class="fb-btn fb-btn-resolved" :disabled="loading" @click="closeIssue('resolved')">
            以解决关闭
          </button>
          <button class="fb-btn fb-btn-dismissed" :disabled="loading" @click="closeIssue('dismissed')">
            不处理关闭
          </button>
          <button class="fb-btn fb-btn-reopen" :disabled="loading" @click="reopenIssue">
            重新打开
          </button>
        </div>
        <div class="fb-admin-actions" v-else>
          <button class="fb-btn fb-btn-reopen" :disabled="loading" @click="reopenIssue">
            重新打开
          </button>
          <button class="fb-btn fb-btn-reopen-reply" :disabled="loading || !commentText.trim()" @click="replyAndReopenIssue">
            回复并重新打开
          </button>
        </div>

        <div class="fb-admin-actions fb-admin-delete">
          <button class="fb-btn fb-btn-danger" :disabled="loading" @click="removeIssue">
            删除反馈
          </button>
        </div>

        <div class="fb-comment-form">
          <textarea
            v-model="commentText"
            class="fb-comment-input"
            rows="3"
            placeholder="以管理员身份回复...（点「回复并重新打开」可一并重开该反馈）"
            :disabled="loading"
          ></textarea>
          <button class="fb-btn fb-btn-primary" :disabled="loading || !commentText.trim()" @click="submitComment">
            回复
          </button>
        </div>
      </div>
    </section>

    <!-- 新建视图 -->
    <section v-else-if="view === 'new'" class="fb-body fb-new">
      <button class="fb-back" @click="backToList">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
        返回列表
      </button>

      <h2 class="fb-new-title">新建反馈</h2>
      <p class="fb-new-desc">功能建议、Bug 反馈或其他意见，欢迎告诉我们。</p>

      <div class="fb-form-group">
        <label>类型</label>
        <div class="fb-type-select">
          <button
            v-for="(meta, key) in typeMeta"
            :key="key"
            type="button"
            class="fb-type-option"
            :class="[key, { active: newType === key }]"
            @click="newType = key as any"
          >
            {{ meta.label }}
          </button>
        </div>
      </div>
      <div class="fb-form-group">
        <label>标题</label>
        <input v-model="newTitle" class="fb-input" type="text" placeholder="一句话概括（选填）" :disabled="submitting" />
      </div>
      <div class="fb-form-group">
        <label>内容</label>
        <textarea
          v-model="newContent"
          class="fb-textarea"
          rows="7"
          placeholder="请详细描述（选填，与标题至少填一项）"
          :disabled="submitting"
        ></textarea>
        <div class="char-count">{{ newContent.length }}/2000</div>
      </div>
      <div class="fb-form-group">
        <label>联系方式（选填）</label>
        <input v-model="newContact" class="fb-input" type="text" placeholder="邮箱或联系方式，方便我们回复" :disabled="submitting" />
      </div>

      <div v-if="formMsg" class="fb-form-msg">{{ formMsg }}</div>

      <div class="fb-new-footer">
        <button class="fb-btn fb-btn-secondary" :disabled="submitting" @click="backToList">取消</button>
        <button class="fb-btn fb-btn-primary" :disabled="submitting" @click="submitNew">
          {{ submitting ? '提交中...' : '提交' }}
        </button>
      </div>
    </section>
  </div>
</template>

<style scoped>
.fb-page {
  max-width: 920px;
  margin: 0 auto;
  padding: 20px 24px 60px;
  min-height: 100%;
}
.fb-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 0 16px;
  border-bottom: 1px solid var(--border-default);
  margin-bottom: 16px;
}
.fb-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}
.fb-title svg { color: #58a6ff; }
.fb-title small {
  font-size: 13px;
  font-weight: 400;
  color: var(--text-secondary);
  margin-left: 10px;
}

.fb-body { min-height: 200px; }

/* 工具栏 */
.fb-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.fb-tabs { display: flex; gap: 4px; }
.fb-tab {
  background: transparent;
  border: 1px solid transparent;
  color: var(--text-secondary);
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.fb-tab:hover { background: var(--bg-surface-hover); color: var(--text-primary); }
.fb-tab.active {
  background: var(--bg-surface-hover);
  border-color: var(--border-default);
  color: var(--text-primary);
}
.fb-tab-count {
  background: var(--bg-surface-hover);
  border-radius: 10px;
  padding: 0 6px;
  font-size: 11px;
  margin-left: 2px;
}
.fb-toolbar-right { display: flex; gap: 8px; align-items: center; }
.fb-search {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  color: var(--text-primary);
  padding: 7px 10px;
  font-size: 13px;
  width: 200px;
  outline: none;
}
.fb-search:focus { border-color: #58a6ff; }
.fb-new-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  background: var(--accent);
  border: 1px solid rgba(255,255,255,0.1);
  color: var(--text-on-accent);
  padding: 7px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}
.fb-new-btn:hover { background: var(--accent-hover); }

/* 列表 */
.fb-loading, .fb-empty, .fb-error {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px 0;
  font-size: 14px;
}
.fb-error { color: #ff7b72; }
.fb-list { list-style: none; }
.fb-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 8px;
  border-top: 1px solid var(--border-default);
  cursor: pointer;
}
.fb-item:first-child { border-top: none; }
.fb-item:hover { background: var(--bg-surface-hover); }
.fb-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  margin-top: 3px;
  flex-shrink: 0;
}
.fb-dot.open { background: var(--success); }
.fb-dot.in_progress { background: #58a6ff; }
.fb-dot.pending { background: #d29922; }
.fb-dot.resolved { background: #a371f7; }
.fb-dot.dismissed { background: #6e7681; }
.fb-item-main { flex: 1; min-width: 0; }
.fb-item-title {
  color: var(--text-primary);
  font-size: 15px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fb-item:hover .fb-item-title { color: #58a6ff; }
.fb-item-meta {
  color: var(--text-secondary);
  font-size: 12px;
  margin-top: 4px;
}
.fb-comment-badge {
  margin-left: 8px;
  background: var(--bg-surface-hover);
  border-radius: 10px;
  padding: 1px 8px;
}

/* 详情 */
.fb-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  margin-bottom: 12px;
  padding: 4px 0;
}
.fb-back:hover { color: #58a6ff; }
.fb-detail-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-wrap: wrap;
}
.fb-detail-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}
.fb-detail-id { color: var(--text-secondary); font-size: 16px; }
.fb-status-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
  flex-wrap: wrap;
}
.fb-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 12px;
  border-radius: 20px;
  font-size: 13px;
  font-weight: 600;
}
.fb-badge.open { background: rgba(63,185,80,0.15); color: #3fb950; }
.fb-badge.in_progress { background: rgba(88,166,255,0.15); color: #58a6ff; }
.fb-badge.pending { background: rgba(210,153,34,0.15); color: #d29922; }
.fb-badge.resolved { background: rgba(163,113,247,0.15); color: #a371f7; }
.fb-badge.dismissed { background: rgba(110,118,129,0.2); color: var(--text-secondary); }
.fb-badge-ico { display: inline-flex; }
.fb-detail-meta { color: var(--text-secondary); font-size: 12px; }

.fb-content-box {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.fb-content {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}
.fb-contact {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed var(--border-default);
  color: var(--text-secondary);
  font-size: 13px;
}

.fb-comments { margin-bottom: 18px; }
.fb-comments-title {
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}
.fb-comment {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 12px 14px;
  margin-bottom: 10px;
}
.fb-comment-head {
  display: flex;
  gap: 10px;
  align-items: baseline;
  margin-bottom: 6px;
}
.fb-comment-author { color: #58a6ff; font-weight: 600; font-size: 13px; }
.fb-comment-time { color: var(--text-secondary); font-size: 12px; }
.fb-comment-content {
  color: var(--text-secondary);
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

/* 管理员操作 */
.fb-admin {
  border-top: 1px solid var(--border-default);
  padding-top: 16px;
}
.fb-admin-status {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.fb-admin-status-label {
  color: var(--text-secondary);
  font-size: 13px;
}
.fb-status-select {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  color: var(--text-primary);
  padding: 7px 10px;
  font-size: 13px;
  outline: none;
  cursor: pointer;
}
.fb-status-select:focus { border-color: #58a6ff; }
.fb-status-select:disabled { opacity: 0.5; cursor: not-allowed; }
.fb-admin-status-ok {
  color: #3fb950;
  font-size: 12px;
}
.fb-admin-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.fb-btn {
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  border: 1px solid transparent;
  font-weight: 500;
}
.fb-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.fb-btn-primary { background: var(--accent); color: var(--text-on-accent); }
.fb-btn-primary:hover:not(:disabled) { background: var(--accent-hover); }
.fb-btn-secondary { background: var(--bg-surface-hover); color: var(--text-primary); border-color: var(--border-default); }
.fb-btn-secondary:hover:not(:disabled) { background: var(--bg-surface-hover); }
.fb-btn-pending { background: rgba(210,153,34,0.15); color: #d29922; border-color: rgba(210,153,34,0.4); }
.fb-btn-pending:hover:not(:disabled) { background: rgba(210,153,34,0.25); }
.fb-btn-resolved { background: rgba(163,113,247,0.15); color: #a371f7; border-color: rgba(163,113,247,0.4); }
.fb-btn-resolved:hover:not(:disabled) { background: rgba(163,113,247,0.25); }
.fb-btn-dismissed { background: rgba(110,118,129,0.15); color: var(--text-secondary); border-color: rgba(110,118,129,0.4); }
.fb-btn-dismissed:hover:not(:disabled) { background: rgba(110,118,129,0.25); }
.fb-btn-reopen { background: rgba(63,185,80,0.15); color: #3fb950; border-color: rgba(63,185,80,0.4); }
.fb-btn-reopen:hover:not(:disabled) { background: rgba(63,185,80,0.25); }
.fb-btn-reopen-reply { background: rgba(88,166,255,0.15); color: #58a6ff; border-color: rgba(88,166,255,0.4); }
.fb-btn-reopen-reply:hover:not(:disabled) { background: rgba(88,166,255,0.25); }
.fb-btn-danger { background: rgba(248,81,73,0.15); color: #f85149; border-color: rgba(248,81,73,0.45); }
.fb-btn-danger:hover:not(:disabled) { background: rgba(248,81,73,0.28); }
.fb-admin-delete { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--border-default); }

.fb-comment-form { display: flex; gap: 10px; align-items: flex-start; }
.fb-comment-input {
  flex: 1;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  color: var(--text-primary);
  padding: 10px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  outline: none;
}
.fb-comment-input:focus { border-color: #58a6ff; }

/* 新建 */
.fb-new-title { font-size: 18px; color: var(--text-primary); margin: 4px 0 6px; }
.fb-new-desc { color: var(--text-secondary); font-size: 13px; margin-bottom: 18px; }
.fb-form-group { margin-bottom: 16px; }
.fb-form-group label {
  display: block;
  color: var(--text-secondary);
  font-size: 13px;
  margin-bottom: 6px;
}
.required { color: #ff7b72; }
.fb-input, .fb-textarea {
  width: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 6px;
  color: var(--text-primary);
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  outline: none;
}
.fb-textarea { resize: vertical; }
.fb-input:focus, .fb-textarea:focus { border-color: #58a6ff; }
.fb-input:disabled, .fb-textarea:disabled { opacity: 0.6; }
.char-count { text-align: right; font-size: 12px; color: #6e7681; margin-top: 4px; }
.fb-form-msg {
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 13px;
  margin-bottom: 14px;
  background: rgba(248,81,73,0.12);
  color: #ff7b72;
  border: 1px solid rgba(248,81,73,0.3);
}
.fb-new-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 8px;
}

/* 类型过滤栏 */
.fb-type-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 14px;
}
.fb-type-tab {
  background: transparent;
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  padding: 5px 14px;
  border-radius: 999px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s ease;
}
.fb-type-tab:hover { color: var(--text-primary); border-color: var(--text-secondary); }
.fb-type-tab.active { color: var(--text-primary); border-color: transparent; }
.fb-type-tab.bug.active { background: #f85149; }
.fb-type-tab.suggestion.active { background: #58a6ff; }
.fb-type-tab.other.active { background: var(--text-secondary); }

/* 类型徽章 */
.fb-type-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.6;
  vertical-align: middle;
}
.fb-type-badge.type-bug { background: rgba(248,81,73,0.15); color: #ff7b72; }
.fb-type-badge.type-suggestion { background: rgba(88,166,255,0.15); color: #58a6ff; }
.fb-type-badge.type-other { background: rgba(139,148,158,0.15); color: var(--text-secondary); }

/* 新建：类型选择 */
.fb-type-select { display: flex; flex-wrap: wrap; gap: 8px; }
.fb-type-option {
  background: transparent;
  border: 1px solid var(--border-default);
  color: var(--text-secondary);
  padding: 7px 18px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s ease;
}
.fb-type-option:hover { color: var(--text-primary); border-color: var(--text-secondary); }
.fb-type-option.active { color: var(--text-primary); border-color: transparent; }
.fb-type-option.bug.active { background: #f85149; }
.fb-type-option.suggestion.active { background: #58a6ff; }
.fb-type-option.other.active { background: var(--text-secondary); }

@media (max-width: 600px) {
  .fb-page { padding: 14px 14px 40px; }
  .fb-toolbar { flex-direction: column; align-items: stretch; }
  .fb-toolbar-right { flex-direction: column; align-items: stretch; }
  .fb-search { width: 100%; }
  .fb-new-btn { justify-content: center; }
}
</style>
