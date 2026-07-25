<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import {
  getIssues,
  getIssue,
  createIssue,
  updateIssue,
  addIssueComment,
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
const closedCount = ref(0)
const statusFilter = ref<'all' | 'open' | 'closed'>('all')
const keyword = ref('')
const page = ref(1)
const pageSize = 20

const selected = ref<Issue | null>(null)
const commentText = ref('')

const newTitle = ref('')
const newContent = ref('')
const newContact = ref('')
const submitting = ref(false)
const formMsg = ref('')

const tabs = computed(() => [
  { key: 'all', label: '全部', count: total.value },
  { key: 'open', label: '开放', count: openCount.value },
  { key: 'closed', label: '已关闭', count: closedCount.value },
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

function openNew() {
  newTitle.value = ''
  newContent.value = ''
  newContact.value = ''
  formMsg.value = ''
  view.value = 'new'
}

async function submitNew() {
  if (!newContent.value.trim()) {
    formMsg.value = '请输入内容'
    return
  }
  if (newContent.value.trim().length < 5) {
    formMsg.value = '内容太短，请详细描述'
    return
  }
  submitting.value = true
  formMsg.value = ''
  try {
    const res = await createIssue({
      title: newTitle.value.trim(),
      content: newContent.value.trim(),
      contact: newContact.value.trim() || undefined,
    })
    if (res.success) {
      view.value = 'list'
      await loadIssues(true)
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

watch([statusFilter, keyword], () => loadIssues(true))

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
        <small v-if="view === 'list'">开放 {{ openCount }} · 已关闭 {{ closedCount }}</small>
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
            @click="statusFilter = t.key as any"
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
            :class="it.status === 'open' ? 'open' : (it.closed_reason === 'resolved' ? 'resolved' : 'dismissed')"
          ></span>
          <div class="fb-item-main">
            <div class="fb-item-title">{{ it.title }}</div>
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
          :class="selected.status === 'open' ? 'open' : (selected.closed_reason === 'resolved' ? 'resolved' : 'dismissed')"
        >
          <span class="fb-badge-ico">
            <svg v-if="selected.status === 'open'" width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="8"/></svg>
            <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/></svg>
          </span>
          {{ selected.status === 'open' ? '开放' : (selected.closed_reason === 'resolved' ? '已解决' : '已关闭') }}
        </span>
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
        <div class="fb-admin-actions" v-if="selected.status === 'open'">
          <button class="fb-btn fb-btn-resolved" :disabled="loading" @click="closeIssue('resolved')">
            以解决关闭
          </button>
          <button class="fb-btn fb-btn-dismissed" :disabled="loading" @click="closeIssue('dismissed')">
            不处理关闭
          </button>
        </div>
        <div class="fb-admin-actions" v-else>
          <button class="fb-btn fb-btn-reopen" :disabled="loading" @click="reopenIssue">
            重新打开
          </button>
        </div>

        <div class="fb-comment-form">
          <textarea
            v-model="commentText"
            class="fb-comment-input"
            rows="3"
            placeholder="以管理员身份回复..."
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
      <p class="fb-new-desc">功能建议、Bug 反馈或改进意见，欢迎告诉我们。</p>

      <div class="fb-form-group">
        <label>标题 <span class="required">*</span></label>
        <input v-model="newTitle" class="fb-input" type="text" placeholder="一句话概括你的建议" :disabled="submitting" />
      </div>
      <div class="fb-form-group">
        <label>内容 <span class="required">*</span></label>
        <textarea
          v-model="newContent"
          class="fb-textarea"
          rows="7"
          placeholder="请详细描述..."
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
  border-bottom: 1px solid #30363d;
  margin-bottom: 16px;
}
.fb-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 20px;
  font-weight: 600;
  color: #e6edf3;
}
.fb-title svg { color: #58a6ff; }
.fb-title small {
  font-size: 13px;
  font-weight: 400;
  color: #8b949e;
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
  color: #8b949e;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
}
.fb-tab:hover { background: #21262d; color: #e6edf3; }
.fb-tab.active {
  background: #21262d;
  border-color: #30363d;
  color: #e6edf3;
}
.fb-tab-count {
  background: #30363d;
  border-radius: 10px;
  padding: 0 6px;
  font-size: 11px;
  margin-left: 2px;
}
.fb-toolbar-right { display: flex; gap: 8px; align-items: center; }
.fb-search {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 6px;
  color: #e6edf3;
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
  background: #238636;
  border: 1px solid rgba(255,255,255,0.1);
  color: #fff;
  padding: 7px 12px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}
.fb-new-btn:hover { background: #2ea043; }

/* 列表 */
.fb-loading, .fb-empty, .fb-error {
  text-align: center;
  color: #8b949e;
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
  border-top: 1px solid #21262d;
  cursor: pointer;
}
.fb-item:first-child { border-top: none; }
.fb-item:hover { background: #1c2128; }
.fb-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  margin-top: 3px;
  flex-shrink: 0;
}
.fb-dot.open { background: #3fb950; }
.fb-dot.resolved { background: #a371f7; }
.fb-dot.dismissed { background: #6e7681; }
.fb-item-main { flex: 1; min-width: 0; }
.fb-item-title {
  color: #e6edf3;
  font-size: 15px;
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.fb-item:hover .fb-item-title { color: #58a6ff; }
.fb-item-meta {
  color: #8b949e;
  font-size: 12px;
  margin-top: 4px;
}
.fb-comment-badge {
  margin-left: 8px;
  background: #21262d;
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
  color: #8b949e;
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
  color: #e6edf3;
  margin: 0;
}
.fb-detail-id { color: #8b949e; font-size: 16px; }
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
.fb-badge.resolved { background: rgba(163,113,247,0.15); color: #a371f7; }
.fb-badge.dismissed { background: rgba(110,118,129,0.2); color: #8b949e; }
.fb-badge-ico { display: inline-flex; }
.fb-detail-meta { color: #8b949e; font-size: 12px; }

.fb-content-box {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 18px;
}
.fb-content {
  color: #c9d1d9;
  font-size: 14px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}
.fb-contact {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px dashed #30363d;
  color: #8b949e;
  font-size: 13px;
}

.fb-comments { margin-bottom: 18px; }
.fb-comments-title {
  color: #8b949e;
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
}
.fb-comment {
  background: #0d1117;
  border: 1px solid #30363d;
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
.fb-comment-time { color: #8b949e; font-size: 12px; }
.fb-comment-content {
  color: #c9d1d9;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

/* 管理员操作 */
.fb-admin {
  border-top: 1px solid #30363d;
  padding-top: 16px;
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
.fb-btn-primary { background: #238636; color: #fff; }
.fb-btn-primary:hover:not(:disabled) { background: #2ea043; }
.fb-btn-secondary { background: #21262d; color: #e6edf3; border-color: #30363d; }
.fb-btn-secondary:hover:not(:disabled) { background: #30363d; }
.fb-btn-resolved { background: rgba(163,113,247,0.15); color: #a371f7; border-color: rgba(163,113,247,0.4); }
.fb-btn-resolved:hover:not(:disabled) { background: rgba(163,113,247,0.25); }
.fb-btn-dismissed { background: rgba(110,118,129,0.15); color: #8b949e; border-color: rgba(110,118,129,0.4); }
.fb-btn-dismissed:hover:not(:disabled) { background: rgba(110,118,129,0.25); }
.fb-btn-reopen { background: rgba(63,185,80,0.15); color: #3fb950; border-color: rgba(63,185,80,0.4); }
.fb-btn-reopen:hover:not(:disabled) { background: rgba(63,185,80,0.25); }

.fb-comment-form { display: flex; gap: 10px; align-items: flex-start; }
.fb-comment-input {
  flex: 1;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 6px;
  color: #e6edf3;
  padding: 10px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  outline: none;
}
.fb-comment-input:focus { border-color: #58a6ff; }

/* 新建 */
.fb-new-title { font-size: 18px; color: #e6edf3; margin: 4px 0 6px; }
.fb-new-desc { color: #8b949e; font-size: 13px; margin-bottom: 18px; }
.fb-form-group { margin-bottom: 16px; }
.fb-form-group label {
  display: block;
  color: #c9d1d9;
  font-size: 13px;
  margin-bottom: 6px;
}
.required { color: #ff7b72; }
.fb-input, .fb-textarea {
  width: 100%;
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 6px;
  color: #e6edf3;
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

@media (max-width: 600px) {
  .fb-page { padding: 14px 14px 40px; }
  .fb-toolbar { flex-direction: column; align-items: stretch; }
  .fb-toolbar-right { flex-direction: column; align-items: stretch; }
  .fb-search { width: 100%; }
  .fb-new-btn { justify-content: center; }
}
</style>
