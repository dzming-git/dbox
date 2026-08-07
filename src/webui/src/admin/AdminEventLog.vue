<template>
  <div class="card">
    <div class="card-header">
      <h3>事件日志</h3>
      <div class="header-actions">
        <label class="auto-refresh">
          <input type="checkbox" v-model="autoRefresh" @change="toggleAutoRefresh" />
          自动刷新
        </label>
        <button class="btn btn-ghost" @click="clearLog" :disabled="loading || clearing">清空</button>
        <button class="btn btn-primary" @click="loadLog" :disabled="loading">刷新</button>
      </div>
    </div>

    <div class="event-status" :class="running ? 'on' : 'off'">
      监听器状态：<b>{{ running ? '运行中' : '未运行' }}</b>
      <span class="hint" v-if="!running">（事件监听器是独立常驻服务，请在「服务管理」中启动）</span>
    </div>

    <!-- 事件处理器清单 -->
    <div class="handlers-panel">
      <div class="handlers-title">
        已注册的事件处理器
        <span class="count">({{ handlers.length }})</span>
        <button class="btn btn-sm btn-ghost" @click="loadHandlers" :disabled="loadingHandlers">重新加载</button>
      </div>
      <div v-if="loadingHandlers" class="empty-tip">加载中…</div>
      <div v-else-if="handlers.length === 0" class="empty-tip">暂无已注册的事件处理器</div>
      <div v-else class="handlers-grid">
        <div v-for="h in handlers" :key="h.event" class="handler-card" :class="{ disabled: !h.enabled }">
          <div class="handler-head">
            <span class="handler-event">{{ h.event }}</span>
            <span class="handler-badge" :class="h.enabled ? 'on' : 'off'">
              {{ h.enabled ? '已配置' : '未配置' }}
            </span>
          </div>
          <div class="handler-desc" v-if="h.description">{{ h.description }}</div>
          <div class="handler-scripts">
            <div v-if="h.handlers.length === 0" class="no-script">未绑定处理器</div>
            <div v-for="(s, i) in h.handlers" :key="i" class="script-line">
              <code>{{ s.script }}</code>
              <span v-if="s.args && s.args.length" class="script-args">{{ s.args.join(' ') }}</span>
            </div>
          </div>
          <div class="handler-filter">
            <button class="btn btn-sm" @click="filterByEvent(h.event)"
              :class="{ active: filterEvent === h.event }">
              {{ filterEvent === h.event ? '取消筛选' : '筛选日志' }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <div class="event-toolbar">
      <label>查看模式：</label>
      <select v-model="mode" @change="onModeChange">
        <option value="tail">末尾 N 行</option>
        <option value="page">分页</option>
      </select>
      <template v-if="mode === 'tail'">
        <input class="tail-input" type="number" min="10" max="2000" v-model.number="tail" @change="loadLog" />
        <span>行</span>
      </template>
      <template v-else>
        <span>第 {{ page }} / {{ totalPages }} 页</span>
        <button class="btn btn-sm" @click="prevPage" :disabled="page <= 1">上一页</button>
        <button class="btn btn-sm" @click="nextPage" :disabled="page >= totalPages">下一页</button>
      </template>
      <span class="filter-tag" v-if="filterEvent">
        筛选：{{ filterEvent }}
        <button class="btn btn-sm btn-ghost" @click="clearFilter">清除</button>
      </span>
      <span class="total-tag" v-if="filterEvent">共 {{ total }} 条</span>
    </div>

    <div v-if="loading" class="empty-tip">加载中…</div>
    <div v-else-if="lines.length === 0" class="empty-state">
      <p v-if="filterEvent">当前筛选「{{ filterEvent }}」下暂无日志。</p>
      <p v-else>暂无日志。监听器启动并处理反馈事件后，这里会显示处理过程。</p>
    </div>
    <div v-else class="log-viewer">
      <pre class="log-content"><div v-for="(line, i) in lines" :key="i" class="log-line">{{ line }}</div></pre>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { eventApi } from '../api'
import { useToast } from '../composables/useToast'

const { showToast } = useToast()

const lines = ref<string[]>([])
const loading = ref(false)
const running = ref(false)
const mode = ref<'tail' | 'page'>('tail')
const tail = ref(100)
const page = ref(1)
const limit = ref(100)
const total = ref(0)
const autoRefresh = ref(false)
const filterEvent = ref<string | null>(null)
let timer: number | null = null

// 事件处理器清单
const handlers = ref<any[]>([])
const loadingHandlers = ref(false)
const clearing = ref(false)

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))

async function loadStatus() {
  try {
    const res = await eventApi.getStatus()
    running.value = !!(res && (res as any).running)
  } catch (e) {
    running.value = false
  }
}

async function loadHandlers() {
  loadingHandlers.value = true
  try {
    const res = await eventApi.getHandlers()
    if (res && (res as any).success) {
      handlers.value = (res as any).handlers || []
    }
  } catch (e: any) {
    showToast('加载事件处理器失败：' + (e?.message || e))
  } finally {
    loadingHandlers.value = false
  }
}

async function loadLog() {
  loading.value = true
  try {
    const params: any = {}
    if (mode.value === 'tail') {
      params.tail = tail.value
    } else {
      params.page = page.value
      params.limit = limit.value
    }
    if (filterEvent.value) {
      params.event = filterEvent.value
    }
    const res = await eventApi.getLog(params)
    if (res && (res as any).success) {
      lines.value = (res as any).lines || []
      total.value = (res as any).total || 0
    } else {
      showToast((res as any).message || '加载事件日志失败')
    }
  } catch (e: any) {
    showToast('加载事件日志失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function clearLog() {
  if (clearing.value) return
  clearing.value = true
  try {
    const res = await eventApi.clearLog()
    if (res && (res as any).success) {
      lines.value = []
      total.value = 0
      filterEvent.value = null
      showToast('事件日志已清空')
    } else {
      showToast((res as any).message || '清空失败')
    }
  } catch (e: any) {
    showToast('清空事件日志失败：' + (e?.message || e))
  } finally {
    clearing.value = false
  }
}

function filterByEvent(ev: string) {
  if (filterEvent.value === ev) {
    clearFilter()
    return
  }
  filterEvent.value = ev
  page.value = 1
  loadLog()
}

function clearFilter() {
  filterEvent.value = null
  page.value = 1
  loadLog()
}

function onModeChange() {
  page.value = 1
  loadLog()
}

function prevPage() {
  if (page.value > 1) {
    page.value--
    loadLog()
  }
}

function nextPage() {
  if (page.value < totalPages.value) {
    page.value++
    loadLog()
  }
}

function toggleAutoRefresh() {
  if (autoRefresh.value) {
    timer = window.setInterval(() => { loadLog(); loadStatus() }, 5000)
  } else if (timer) {
    clearInterval(timer)
    timer = null
  }
}

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

loadLog()
loadStatus()
loadHandlers()
</script>

<style scoped>
.event-status {
  padding: 8px 12px;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
}
.event-status.on {
  background: rgba(40, 167, 69, 0.12);
  color: #2e9e4b;
}
.event-status.off {
  background: rgba(255, 193, 7, 0.12);
  color: #b8860b;
}
.event-status .hint {
  color: var(--text-muted, #888);
  font-weight: normal;
  margin-left: 6px;
}
.handlers-panel {
  border: 1px solid var(--border-color, #ddd);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 14px;
  background: var(--bg-subtle, #fafafa);
}
.handlers-title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 10px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.handlers-title .count {
  color: var(--text-muted, #888);
  font-weight: normal;
}
.handlers-title .btn {
  margin-left: auto;
}
.handlers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 10px;
}
.handler-card {
  border: 1px solid var(--border-color, #e0e0e0);
  border-radius: 6px;
  padding: 10px;
  background: #fff;
  font-size: 12px;
}
.handler-card.disabled {
  opacity: 0.7;
}
.handler-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.handler-event {
  font-family: 'Consolas', 'Monaco', monospace;
  font-weight: 600;
  color: var(--text, #333);
}
.handler-badge {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
}
.handler-badge.on {
  background: rgba(40, 167, 69, 0.15);
  color: #2e9e4b;
}
.handler-badge.off {
  background: rgba(255, 193, 7, 0.15);
  color: #b8860b;
}
.handler-desc {
  color: var(--text-muted, #888);
  margin-bottom: 6px;
}
.handler-scripts .no-script {
  color: var(--text-muted, #aaa);
  font-style: italic;
}
.script-line {
  font-family: 'Consolas', 'Monaco', monospace;
  background: #f5f5f5;
  border-radius: 4px;
  padding: 3px 6px;
  margin-bottom: 4px;
  word-break: break-all;
}
.script-line code {
  color: #c7254e;
}
.script-args {
  color: var(--text-muted, #888);
  margin-left: 6px;
}
.handler-filter {
  margin-top: 8px;
}
.handler-filter .btn.active {
  background: var(--primary, #007bff);
  color: #fff;
  border-color: var(--primary, #007bff);
}
.event-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  font-size: 13px;
  flex-wrap: wrap;
}
.event-toolbar select,
.event-toolbar .tail-input {
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color, #ddd);
  width: auto;
}
.event-toolbar .tail-input {
  width: 90px;
}
.filter-tag {
  background: rgba(0, 123, 255, 0.12);
  color: #007bff;
  padding: 2px 8px;
  border-radius: 4px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.total-tag {
  color: var(--text-muted, #888);
}
.log-viewer {
  background: #1e1e1e;
  border-radius: 6px;
  padding: 12px;
  max-height: 55vh;
  overflow: auto;
}
.log-content {
  margin: 0;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
  color: #d4d4d4;
  white-space: pre-wrap;
  word-break: break-all;
}
.log-line {
  padding: 1px 0;
}
.auto-refresh {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}
.btn-sm {
  padding: 4px 10px;
  font-size: 12px;
}
.btn-ghost {
  background: transparent;
  border: 1px solid var(--border-color, #ddd);
}
.empty-tip,
.empty-state {
  padding: 16px;
  color: var(--text-muted, #888);
  font-size: 13px;
}
</style>
