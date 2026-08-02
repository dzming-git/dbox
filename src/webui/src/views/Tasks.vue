<template>
  <div class="tasks-page">
    <div class="page-header">
      <h2>任务管理器</h2>
      <button class="refresh-btn" @click="refresh" :disabled="loading">刷新</button>
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
        </div>

        <div class="task-progress">
          <div class="bar" :style="{ width: clampProgress(t.progress) + '%' }"></div>
        </div>
        <div class="task-meta">
          <span>{{ clampProgress(t.progress) }}%</span>
          <span v-if="t.stage">· {{ t.stage }}</span>
          <span v-if="t.detail" class="task-detail">· {{ t.detail }}</span>
        </div>

        <div v-if="t.action_required" class="task-action">
          <button class="handle-btn" @click="handleTask(t)">
            <span class="dot"></span> 需要处理：{{ t.action_hint || '点击处理' }}
          </button>
        </div>

        <div class="task-time">{{ formatTime(t.updated_at) }}</div>
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
import { scriptApi, type PendingInput } from '../api/script'

const router = useRouter()
const tasks = ref<Task[]>([])
const actionCount = ref(0)
const loading = ref(false)

let pollTimer: any = null

// 交互弹窗状态
const interaction = ref<PendingInput | null>(null)
const interactionValue = ref<any>('')
const interactionText = ref('')
const currentJobId = ref<string | null>(null)
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

async function handleTask(t: Task) {
  if (t.action_kind === 'navigate' && t.action_data?.url) {
    router.push(t.action_data.url)
    return
  }
  if (t.action_kind === 'script_interactive' && t.action_data?.job_id) {
    currentJobId.value = t.action_data.job_id
    // 先尝试拉取脚本任务的交互详情；失败则仅展示提示信息，不阻塞处理弹窗。
    try {
      const res: any = await scriptApi.getJob(t.action_data.job_id)
      const job = res.job
      if (job && job.pending_input) {
        interaction.value = job.pending_input
        interactionValue.value = job.pending_input.multi ? [] : ''
        interactionText.value = ''
      } else {
        interaction.value = {
          kind: 'text',
          prompt: t.action_hint || '该任务需要你处理',
        }
        interactionValue.value = ''
        interactionText.value = ''
      }
    } catch (e: any) {
      interaction.value = {
        kind: 'text',
        prompt: t.action_hint || '该任务需要你处理',
      }
      interactionValue.value = ''
      interactionText.value = ''
    }
  }
}

function closeInteraction() {
  interaction.value = null
  currentJobId.value = null
  interactionValue.value = ''
  interactionText.value = ''
}

async function submitInteraction() {
  if (!interaction.value || !currentJobId.value) return
  let val: any
  if (interaction.value.multi) {
    val = Array.isArray(interactionValue.value) ? [...interactionValue.value] : []
    if (interaction.value.allow_text && interactionText.value.trim()) {
      val.push(interactionText.value.trim())
    }
    if (!val.length) {
      alert('请至少选择一项')
      return
    }
  } else if (interaction.value.allow_text && interactionText.value.trim()) {
    val = interactionText.value.trim()
  } else {
    val = interactionValue.value
    if (!val) {
      alert('请选择一项')
      return
    }
  }
  submitting.value = true
  try {
    await scriptApi.respondJob(currentJobId.value, val)
    closeInteraction()
    refresh()
  } catch (e: any) {
    alert('提交失败：' + (e?.message || e))
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  refresh()
  pollTimer = setInterval(refresh, 2500)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
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
.refresh-btn {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--bg-surface-2);
  border-radius: 8px;
  padding: 6px 14px;
  cursor: pointer;
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
