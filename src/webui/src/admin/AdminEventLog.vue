<template>
  <div class="card">
    <div class="card-header">
      <h3>事件日志</h3>
      <div class="header-actions">
        <label class="auto-refresh">
          <input type="checkbox" v-model="autoRefresh" @change="toggleAutoRefresh" />
          自动刷新
        </label>
        <button class="btn btn-primary" @click="loadLog" :disabled="loading">刷新</button>
      </div>
    </div>

    <div class="event-status" :class="running ? 'on' : 'off'">
      监听器状态：<b>{{ running ? '运行中' : '未运行' }}</b>
      <span class="hint" v-if="!running">（事件监听器是独立常驻服务，请在「服务管理」中启动）</span>
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
    </div>

    <div v-if="loading" class="empty-tip">加载中…</div>
    <div v-else-if="lines.length === 0" class="empty-state">
      <p>暂无日志。监听器启动并处理反馈事件后，这里会显示处理过程。</p>
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
let timer: number | null = null

const totalPages = computed(() => Math.max(1, Math.ceil(total.value / limit.value)))

async function loadStatus() {
  try {
    const res = await eventApi.getStatus()
    running.value = !!(res && (res as any).running)
  } catch (e) {
    running.value = false
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
.log-viewer {
  background: #1e1e1e;
  border-radius: 6px;
  padding: 12px;
  max-height: 60vh;
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
</style>
