<template>
  <div class="tasks-page">
    <div class="page-header">
      <h2>任务管理器</h2>
      <div class="header-actions">
        <button
          v-if="tasks.some(isFinished)"
          class="refresh-btn"
          :disabled="clearing"
          @click="clearFinished"
          title="删除所有已结束的任务"
        >
          {{ clearing ? '清理中…' : '清理已完成' }}
        </button>
        <button class="refresh-btn" @click="refresh" :disabled="loading">刷新</button>
      </div>
    </div>

    <div v-if="actionCount > 0" class="action-banner">
      <span class="dot"></span>
      有 {{ actionCount }} 个任务待你处理
    </div>

    <div v-if="loading && tasks.length === 0" class="empty-tip">加载中…</div>
    <div v-else-if="tasks.length === 0" class="empty-tip">暂无任务</div>

    <div v-else class="task-list">
      <div v-for="t in tasks" :key="t.task_id" class="task-card" :class="['status-' + t.status]">
        <div class="task-top">
          <span class="task-kind" :class="'kind-' + t.kind">{{ kindLabel(t.kind) }}</span>
          <span class="task-title">{{ t.title }}</span>
          <span class="task-status" :class="'st-' + t.status">{{ statusLabel(t.status) }}</span>
          <!-- 已结束的任务可单条删除（进行中不允许，避免误删） -->
          <button
            v-if="isFinished(t)"
            class="task-delete-btn"
            :disabled="deletingId === t.task_id"
            :title="'删除任务：' + t.title"
            @click="deleteOne(t)"
          >
            {{ deletingId === t.task_id ? '删除中…' : '删除' }}
          </button>
          <!-- 失败/已取消的任务可手动重试 -->
          <button
            v-if="canRetry(t)"
            class="task-retry-btn"
            :disabled="retryingId === t.task_id"
            :title="'重试任务：' + t.title"
            @click="retryOne(t)"
          >
            {{ retryingId === t.task_id ? '重试中…' : '重试' }}
          </button>
        </div>

        <div class="task-progress">
          <div class="bar" :style="{ width: clampProgress(t.progress) + '%' }"></div>
        </div>
        <div class="task-meta">
          <span>{{ clampProgress(t.progress) }}%</span>
          <span v-if="t.stage">· {{ t.stage }}</span>
          <span v-if="t.detail" class="task-detail">· {{ t.detail }}</span>
        </div>

        <!-- 任务关键参数：帮助用户在列表中区分不同任务（如脚本名/目标/文件名） -->
        <div v-if="taskParamPreview(t).length" class="task-params">
          <span v-for="(p, i) in taskParamPreview(t)" :key="i" class="param-chip">
            {{ p }}
          </span>
        </div>

        <div v-if="t.action_required" class="task-action">
          <button class="handle-btn" @click="handleTask(t)">
            <span class="dot"></span> 需要处理：{{ t.action_hint || '点击处理' }}
          </button>
        </div>

        <div class="task-time">{{ formatTime(t.updated_at) }}</div>

        <!-- 实时日志面板：脚本任务可展开查看日志；其他任务可展开查看参数与详情 -->
        <div class="task-logs">
          <button
            class="logs-toggle"
            :class="{ open: expandedTaskId === t.task_id }"
            @click="toggleLogs(t)"
          >
            <span class="arrow">{{ expandedTaskId === t.task_id ? '▼' : '▶' }}</span>
            <span>{{ expandedTaskId === t.task_id ? '收起详情' : '查看详情/日志' }}</span>
          </button>
          <div v-if="expandedTaskId === t.task_id" class="logs-panel" @click.stop>
            <div v-if="loadingLogs === t.task_id" class="logs-loading">加载中…</div>
            <div v-else-if="!taskLogs[t.task_id]" class="logs-empty">暂无日志</div>
            <div v-else>
              <div v-if="taskLogs[t.task_id].params && Object.keys(taskLogs[t.task_id].params).length" class="logs-section">
                <div class="logs-section-title">任务参数</div>
                <pre class="logs-params">{{ formatParams(taskLogs[t.task_id].params) }}</pre>
              </div>
              <div v-else-if="taskLogs[t.task_id].raw_params && Object.keys(taskLogs[t.task_id].raw_params).length" class="logs-section">
                <div class="logs-section-title">任务参数</div>
                <pre class="logs-params">{{ formatParams(taskLogs[t.task_id].raw_params) }}</pre>
              </div>
              <div v-if="taskLogs[t.task_id].logs && taskLogs[t.task_id].logs.length" class="logs-section">
                <div class="logs-section-title">
                  实时日志 <span class="logs-count">({{ taskLogs[t.task_id].logs.length }} 条)</span>
                </div>
                <div class="logs-list">
                  <div
                    v-for="(l, i) in taskLogs[t.task_id].logs"
                    :key="i"
                    class="logs-row"
                    :class="'lv-' + l.level"
                  >
                    <span class="logs-ts">{{ formatLogTs(l.ts) }}</span>
                    <span class="logs-level">{{ l.level }}</span>
                    <span class="logs-msg">{{ l.message }}</span>
                  </div>
                </div>
              </div>
              <div
                v-else-if="taskLogs[t.task_id].error"
                class="logs-section"
              >
                <div class="logs-section-title">错误信息</div>
                <pre class="logs-params">{{ taskLogs[t.task_id].error }}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 脚本交互弹窗 -->
    <div v-if="interaction" class="modal-mask" @click.self="closeInteraction">
      <div class="modal">
        <h3>{{ interaction.prompt || '脚本请求选择' }}</h3>
        <div v-if="interaction.options && interaction.options.length" class="options">
          <label v-for="opt in interaction.options" :key="opt.value" class="opt">
            <input
              v-if="interaction.multi"
              type="checkbox"
              :value="opt.value"
              v-model="interactionValue"
            />
            <input
              v-else
              type="radio"
              :value="opt.value"
              v-model="interactionValue"
            />
            {{ opt.label }}
          </label>
        </div>
        <textarea
          v-if="interaction.allow_text"
          v-model="interactionText"
          :placeholder="interaction.text_hint || '手动输入（可选）'"
          class="text-input"
        ></textarea>
        <div class="modal-actions">
          <button class="primary" @click="submitInteraction" :disabled="submitting">
            {{ submitting ? '提交中…' : '确定' }}
          </button>
          <button @click="closeInteraction">取消</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { taskApi, type Task } from '../api/task'
import { type PendingInput } from '../api/script'

const router = useRouter()
const tasks = ref<Task[]>([])
const actionCount = ref(0)
const loading = ref(false)
// 删除相关状态：deletingId 标记正在单条删除中的任务；clearing 用于批量清理按钮的 loading
const deletingId = ref<string | null>(null)
const clearing = ref(false)
// 重试状态：retryingId 标记正在重试中的任务
const retryingId = ref<string | null>(null)
// 详情/日志展开：仅同时展开一个任务的日志面板，避免日志堆叠刷屏
const expandedTaskId = ref<string | null>(null)
const loadingLogs = ref<string | null>(null)
// 任务日志缓存：taskId -> { logs?: Array; params?: object; error?: string }
const taskLogs = ref<Record<string, { logs?: any[]; params?: Record<string, any>; error?: string }>>({})

let pollTimer: any = null

// 交互弹窗状态
const interaction = ref<PendingInput | null>(null)
const interactionValue = ref<any>('')
const interactionText = ref('')

const submitting = ref(false)

function kindLabel(k: string) {
  return ({ script: '脚本', upload: '上传', thumbnail: '缩略图' } as any)[k] || k
}
function statusLabel(s: string) {
  return (
    {
      pending: '排队中',
      running: '进行中',
      awaiting_input: '等待处理',
      completed: '已完成',
      failed: '失败',
      cancelled: '已取消',
    } as any
  )[s] || s
}
function clampProgress(p: number) {
  p = Number(p) || 0
  return Math.max(0, Math.min(100, p))
}
function formatTime(ts: number) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function refresh() {
  loading.value = true
  try {
    const res: any = await taskApi.list()
    tasks.value = res.tasks || []
    actionCount.value = res.action_required_count || 0
  } catch (e) {
    console.error('加载任务失败', e)
  } finally {
    loading.value = false
  }
}

// 是否处于「已结束」终态：仅这些状态可被删除
const FINISHED_STATUSES = new Set(['completed', 'failed', 'cancelled'])
function isFinished(t: Task): boolean {
  return FINISHED_STATUSES.has(t.status as any)
}

// 失败/已取消的任务可在任务列表手动重试
function canRetry(t: Task): boolean {
  return t.status === 'failed' || t.status === 'cancelled'
}

// 卡片上展示任务关键参数，帮助用户区分不同任务。
// 脚本任务：展示脚本标识 + 关键运行参数；上传任务：展示文件名/标题/目标库。
function taskParamPreview(t: Task): string[] {
  const out: string[] = []
  const p = t.params
  if (t.kind === 'script' && p) {
    if (p.script_id) out.push(`脚本:${p.script_id}`)
    const inner = p.params
    if (inner && typeof inner === 'object') {
      for (const key of ['url', 'target', 'target_modes', 'group', 'quality']) {
        const v = inner[key]
        if (v !== undefined && v !== null && v !== '') {
          out.push(`${key}:${Array.isArray(v) ? v.join(',') : v}`)
        }
      }
    }
  } else if (t.kind === 'upload' && p) {
    if (p.filename) out.push(`文件:${p.filename}`)
    if (p.title) out.push(`标题:${p.title}`)
    if (p.library_id != null) out.push(`库:${p.library_id}`)
  } else if (p && typeof p === 'object') {
    for (const [k, v] of Object.entries(p)) {
      if (v !== undefined && v !== null && v !== '') out.push(`${k}:${v}`)
    }
  }
  return out.slice(0, 4)
}

async function deleteOne(t: Task) {
  if (!isFinished(t) || deletingId.value) return
  if (!confirm(`确定要删除任务「${t.title}」吗？该操作不可撤销。`)) return
  deletingId.value = t.task_id
  try {
    await taskApi.delete(t.task_id)
    // 直接从本地列表移除，避免再发请求
    tasks.value = tasks.value.filter((x) => x.task_id !== t.task_id)
  } catch (e: any) {
    alert('删除失败：' + (e?.message || e))
  } finally {
    deletingId.value = null
  }
}

async function retryOne(t: Task) {
  if (!canRetry(t) || retryingId.value) return
  retryingId.value = t.task_id
  try {
    const res: any = await taskApi.retry(t.task_id)
    if (res && res.success) {
      // 脚本类任务由下载器重新提交并同步回任务表，刷新即可看到新任务
      await refresh()
    } else {
      alert('重试失败：' + (res?.message || '未知错误'))
    }
  } catch (e: any) {
    alert('重试失败：' + (e?.message || e))
  } finally {
    retryingId.value = null
  }
}

async function clearFinished() {
  if (clearing.value) return
  const finished = tasks.value.filter(isFinished)
  if (!finished.length) return
  if (!confirm(`确定要删除全部 ${finished.length} 个已结束的任务吗？该操作不可撤销。`)) return
  clearing.value = true
  let failed = 0
  // 并发删除，逐条处理失败不影响其他
  await Promise.all(
    finished.map(async (t) => {
      try {
        await taskApi.delete(t.task_id)
      } catch (e) {
        failed += 1
      }
    })
  )
  clearing.value = false
  if (failed > 0) {
    alert(`已清理 ${finished.length - failed} 个任务，${failed} 个删除失败，请稍后重试`)
  }
  // 重新拉取，避免本地状态与远端不一致
  await refresh()
}

// 切换任务详情/日志面板的展开状态；展开时按需拉取详情，幂等缓存
async function toggleLogs(t: Task) {
  const tid = t.task_id
  if (expandedTaskId.value === tid) {
    expandedTaskId.value = null
    return
  }
  expandedTaskId.value = tid
  if (taskLogs.value[tid]) return  // 已缓存，无需再请求
  loadingLogs.value = tid
  try {
    const res: any = await taskApi.detail(tid)
    const task = res.task || {}
    taskLogs.value = {
      ...taskLogs.value,
      [tid]: {
        logs: task.logs || [],
        raw_params: task.params || task.action_data?.params || undefined,
        error: task.error || task.detail || undefined,
      },
    }
  } catch (e: any) {
    taskLogs.value = {
      ...taskLogs.value,
      [tid]: { logs: [], error: e?.message || '加载失败' },
    }
  } finally {
    loadingLogs.value = null
  }
}

function formatLogTs(ts: string) {
  if (!ts) return '--:--:--'
  // ts 通常是 "YYYY-MM-DD HH:MM:SS" 格式，取 HH:MM:SS
  const m = /(\d{2}:\d{2}:\d{2})/.exec(String(ts))
  return m ? m[1] : String(ts)
}

function formatParams(params: Record<string, any>) {
  try {
    return JSON.stringify(params, null, 2)
  } catch {
    return String(params)
  }
}

// 正在进行的任务每 2.5s 轮询一次数据，已结束的任务会自动停下
// 展开时如发现对应任务仍在进行中，定时刷新其详情（取最新日志）
let logsPollTimer: any = null
function startLogsPoll() {
  if (logsPollTimer) return
  logsPollTimer = setInterval(async () => {
    const tid = expandedTaskId.value
    if (!tid) return
    const cur = tasks.value.find((x) => x.task_id === tid)
    if (cur && !isFinished(cur)) {
      try {
        const res: any = await taskApi.detail(tid)
        const task = res.task || {}
        taskLogs.value = {
          ...taskLogs.value,
          [tid]: {
            logs: task.logs || [],
            raw_params: task.params || task.action_data?.params || undefined,
            error: task.error || task.detail || undefined,
          },
        }
      } catch {
        // 静默忽略；下一次轮询再试
      }
    }
  }, 3000)
}
function stopLogsPoll() {
  if (logsPollTimer) {
    clearInterval(logsPollTimer)
    logsPollTimer = null
  }
}

async function handleTask(t: Task) {
  if (t.action_kind === 'navigate' && t.action_data?.url) {
    router.push(t.action_data.url)
    return
  }
  // 旧「脚本交互」(script_interactive) 已由拓展插件体系接管：
  // 插件通过统一任务系统的 action 自行实现交互，不再依赖已移除的脚本执行引擎。
}

function closeInteraction() {
  interaction.value = null
  currentJobId.value = null
  interactionValue.value = ''
  interactionText.value = ''
}

async function submitInteraction() {
  if (!interaction.value) return
  // 旧脚本交互提交接口已移除；插件的二次交互由插件后端自行处理。
  alert('该交互类型已升级为拓展插件，请在「扩展管理」中操作。')
  closeInteraction()
}

onMounted(() => {
  refresh()
  pollTimer = setInterval(refresh, 2500)
  startLogsPoll()
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
  stopLogsPoll()
})
</script>

<style scoped>
.tasks-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 16px;
  color: var(--text-secondary);
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.page-header h2 {
  font-size: 20px;
  margin: 0;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.refresh-btn {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  padding: 6px 14px;
  cursor: pointer;
}
.task-delete-btn {
  background: transparent;
  color: var(--text-tertiary);
  border: 1px solid var(--bg-surface-2);
  border-radius: 6px;
  padding: 2px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}
.task-delete-btn:hover:not(:disabled) {
  color: var(--danger);
  border-color: var(--danger);
  background: rgba(255, 90, 106, 0.08);
}
.task-delete-btn:disabled {
  opacity: 0.6;
  cursor: progress;
}
.task-retry-btn {
  background: transparent;
  color: #8fd0ff;
  border: 1px solid rgba(120, 170, 255, 0.5);
  border-radius: 6px;
  padding: 2px 10px;
  font-size: 12px;
  cursor: pointer;
  transition: color 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}
.task-retry-btn:hover:not(:disabled) {
  color: #b3e0ff;
  border-color: #8fd0ff;
  background: rgba(120, 170, 255, 0.08);
}
.task-retry-btn:disabled {
  opacity: 0.6;
  cursor: progress;
}
/* 任务关键参数 chip：帮助区分不同任务 */
.task-params {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.param-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--bg-surface-2);
  color: var(--text-secondary);
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.action-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255, 90, 90, 0.12);
  border: 1px solid rgba(255, 90, 90, 0.4);
  color: #ff9a9a;
  padding: 10px 14px;
  border-radius: 10px;
  margin-bottom: 12px;
}
.empty-tip {
  text-align: center;
  color: var(--text-secondary);
  padding: 40px 0;
}
.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.task-card {
  background: var(--bg-surface-hover);
  border: 1px solid var(--bg-surface-2);
  border-radius: 12px;
  padding: 14px 16px;
}
.task-top {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.task-kind {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--bg-surface-hover);
  color: #8fd0ff;
}
.kind-upload {
  color: #9affc4;
}
.kind-thumbnail {
  color: #ffd479;
}
.task-title {
  flex: 1;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.task-status {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 6px;
}
.st-running, .st-pending {
  background: rgba(120, 170, 255, 0.15);
  color: #8fd0ff;
}
.st-awaiting_input {
  background: rgba(255, 90, 90, 0.15);
  color: #ff9a9a;
}
.st-completed {
  background: rgba(120, 255, 160, 0.15);
  color: #9affc4;
}
.st-failed {
  background: rgba(255, 120, 120, 0.15);
  color: var(--danger);
}
.st-cancelled {
  background: rgba(150, 150, 150, 0.15);
  color: var(--text-secondary);
}
.task-progress {
  height: 6px;
  background: var(--bg-surface-hover);
  border-radius: 4px;
  overflow: hidden;
}
.task-progress .bar {
  height: 100%;
  background: linear-gradient(90deg, #4a8cff, #8fd0ff);
  transition: width 0.4s ease;
}
.status-completed .bar {
  background: linear-gradient(90deg, #2ecc71, #9affc4);
}
.status-failed .bar {
  background: linear-gradient(90deg, #e74c3c, #ff8a8a);
}
.status-awaiting_input .bar {
  background: linear-gradient(90deg, #e67e22, #ffd479);
}
.task-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  font-size: 12px;
  color: var(--text-tertiary);
  margin-top: 6px;
}
.task-detail {
  color: var(--text-tertiary);
}
.task-action {
  margin-top: 10px;
}
.handle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(255, 90, 90, 0.18);
  border: 1px solid rgba(255, 90, 90, 0.5);
  color: #ffb3b3;
  border-radius: 8px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 13px;
}
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff5a5a;
  box-shadow: 0 0 6px #ff5a5a;
}
.task-time {
  font-size: 11px;
  color: var(--text-tertiary);
  margin-top: 8px;
  text-align: right;
}
.task-logs {
  margin-top: 10px;
  border-top: 1px dashed var(--bg-surface-2);
  padding-top: 8px;
}
.logs-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 1px solid var(--bg-surface-2);
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  color: var(--text-tertiary);
  cursor: pointer;
  transition: color 0.18s ease, border-color 0.18s ease;
}
.logs-toggle:hover,
.logs-toggle.open {
  color: var(--accent);
  border-color: var(--accent);
}
.logs-toggle .arrow {
  font-size: 10px;
  line-height: 1;
}
.logs-panel {
  margin-top: 8px;
  background: var(--bg-surface);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  padding: 10px 12px;
  max-height: 360px;
  overflow: auto;
}
.logs-loading,
.logs-empty {
  color: var(--text-tertiary);
  font-size: 12px;
  text-align: center;
  padding: 14px 0;
}
.logs-section + .logs-section {
  margin-top: 10px;
}
.logs-section-title {
  font-size: 12px;
  color: var(--text-tertiary);
  margin-bottom: 6px;
  letter-spacing: 0.4px;
}
.logs-count {
  margin-left: 4px;
  font-weight: 400;
}
.logs-list {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.5;
}
.logs-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  padding: 2px 6px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.02);
}
.logs-row .logs-ts {
  color: var(--text-tertiary);
  flex: 0 0 auto;
}
.logs-row .logs-level {
  flex: 0 0 56px;
  text-align: center;
  padding: 0 6px;
  border-radius: 4px;
  font-size: 11px;
  line-height: 18px;
  background: var(--bg-surface-2);
  color: var(--text-secondary);
}
.logs-row.lv-error .logs-level {
  background: rgba(255, 90, 106, 0.2);
  color: var(--danger);
}
.logs-row.lv-warning .logs-level {
  background: rgba(255, 180, 80, 0.2);
  color: #ffb450;
}
.logs-row .logs-msg {
  flex: 1 1 auto;
  word-break: break-all;
  white-space: pre-wrap;
  color: var(--text-secondary);
}
.logs-params {
  margin: 0;
  padding: 8px 10px;
  border-radius: 6px;
  background: var(--bg-surface-hover);
  font-family: ui-monospace, SFMono-Regular, Consolas, 'Courier New', monospace;
  font-size: 12px;
  color: var(--text-secondary);
  max-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  background: var(--bg-surface);
  border: 1px solid var(--bg-surface-2);
  border-radius: 14px;
  padding: 22px;
  width: 90%;
  max-width: 420px;
}
.modal h3 {
  margin: 0 0 14px;
  font-size: 16px;
}
.options {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}
.opt {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.text-input {
  width: 100%;
  min-height: 64px;
  background: var(--bg-surface);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  color: var(--text-secondary);
  padding: 8px;
  resize: vertical;
  margin-bottom: 12px;
}
.modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
}
.modal-actions button {
  padding: 8px 18px;
  border-radius: 8px;
  border: 1px solid var(--bg-surface-2);
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  cursor: pointer;
}
.modal-actions .primary {
  background: #4a8cff;
  border-color: #4a8cff;
  color: var(--text-on-accent);
}
</style>
