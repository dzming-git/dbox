<template>
  <div class="card">
    <div class="card-header">
      <h3>事件监听配置</h3>
      <div class="header-actions">
        <button class="btn btn-primary" @click="save" :disabled="saving || loading">
          {{ saving ? '保存中…' : '保存并重启服务' }}
        </button>
        <button class="btn" @click="restart" :disabled="restarting">重启监听器</button>
        <button class="btn btn-sm" @click="load" :disabled="loading">重新加载</button>
      </div>
    </div>

    <div v-if="loading" class="empty-tip">加载中…</div>
    <div v-else>
      <div class="field-row">
        <label>轮询间隔（秒）：</label>
        <input type="number" min="5" max="3600" v-model.number="interval" />
        <span class="hint">监听器每隔多少秒扫描一次反馈库（建议 15~60）</span>
      </div>

      <div class="events-block">
        <div v-for="ev in registeredEvents" :key="ev.name" class="event-group">
          <div class="event-title">
            <span class="event-tag">{{ ev.name }}</span>
            <span class="event-source" v-if="ev.source">来源：{{ ev.source }}</span>
            <button class="btn btn-sm" @click="addHandler(ev.name)">+ 添加处理器</button>
          </div>
          <p class="event-desc">{{ ev.description }}</p>
          <p class="event-params" v-if="ev.params && ev.params.length">
            触发参数：<code v-for="p in ev.params" :key="p">{{ p }}</code>
            <code>old_status</code><code>new_status</code><code>id</code>
          </p>

          <div v-if="!form.events[ev] || form.events[ev].length === 0" class="empty-sub">
            当前无处理器（该事件不会触发任何脚本）
          </div>
          <div v-for="(h, i) in form.events[ev]" :key="i" class="handler-row">
            <select v-model="h.script" class="script-select">
              <option value="">— 选择脚本 —</option>
              <option v-for="s in availableScripts" :key="s" :value="s">{{ s }}</option>
              <option v-if="h.script && !availableScripts.includes(h.script)" :value="h.script">
                {{ h.script }}（自定义）
              </option>
            </select>
            <input
              class="args-input"
              type="text"
              v-model="h.argsText"
              placeholder="参数（逗号分隔，支持 {EVENT} {ISSUE_ID} {ISSUE_JSON}）"
            />
            <button class="btn btn-sm btn-danger" @click="removeHandler(ev, i)">删除</button>
          </div>
        </div>
      </div>

      <div class="tip-box">
        <b>使用说明：</b>
        <ul>
          <li>每个事件可配置多个处理器，监听器触发时依次调用。</li>
          <li>脚本路径可下拉选择 handlers 目录下的脚本，也可手动填写绝对路径。</li>
          <li>参数占位符：<code>{EVENT}</code> 事件名、<code>{ISSUE_ID}</code> 反馈 ID、<code>{ISSUE_JSON}</code> 反馈 JSON。</li>
          <li>监听器还会通过环境变量 <code>EVENT_NAME</code> / <code>EVENT_PAYLOAD</code> / <code>DBOX_ROOT</code> 注入上下文，脚本可自行选择读取方式。</li>
          <li>保存后监听器服务会自动重启以使配置生效；脚本文件（handlers/）属本地数据，需自行放置，不入库。</li>
        </ul>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { eventApi } from '../api'
import { useToast } from '../composables/useToast'

const { showToast } = useToast()

const loading = ref(false)
const saving = ref(false)
const restarting = ref(false)

const interval = ref(30)
const registeredEvents = ref<any[]>([])
const availableScripts = ref<string[]>([])
const form = reactive<{ events: Record<string, any[]> }>({ events: {} })

function addHandler(ev: string) {
  if (!form.events[ev]) form.events[ev] = []
  form.events[ev].push({ script: '', argsText: '' })
}

function removeHandler(ev: string, i: number) {
  form.events[ev].splice(i, 1)
}

async function load() {
  loading.value = true
  try {
    const res = await eventApi.getConfig()
    if (res && (res as any).success) {
      const cfg = (res as any).config || {}
      interval.value = cfg.interval ?? 30
      registeredEvents.value = (res as any).registered_events || []
      availableScripts.value = (res as any).available_scripts || []
      const events: Record<string, any[]> = {}
      for (const ev of registeredEvents.value) {
        const list = (cfg.events && cfg.events[ev.name]) || []
        events[ev.name] = list.map((h: any) => ({
          script: h.script || '',
          argsText: Array.isArray(h.args) ? h.args.join(', ') : (h.args || ''),
        }))
      }
      form.events = events
    } else {
      showToast((res as any).message || '加载配置失败')
    }
  } catch (e: any) {
    showToast('加载配置失败：' + (e?.message || e))
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  try {
    const events: Record<string, any[]> = {}
    for (const ev of registeredEvents.value) {
      events[ev.name] = (form.events[ev.name] || [])
        .filter((h) => h.script)
        .map((h) => ({
          script: h.script,
          args: (h.argsText || '')
            .split(',')
            .map((a: string) => a.trim())
            .filter((a: string) => a.length > 0),
        }))
    }
    const res = await eventApi.saveConfig({ interval: interval.value, events })
    if (res && (res as any).success) {
      showToast((res as any).message || '已保存')
    } else {
      showToast((res as any).message || '保存失败')
    }
  } catch (e: any) {
    showToast('保存失败：' + (e?.message || e))
  } finally {
    saving.value = false
  }
}

async function restart() {
  restarting.value = true
  try {
    const res = await eventApi.restart()
    if (res && (res as any).success) {
      showToast((res as any).message || '重启成功')
    } else {
      showToast((res as any).message || '重启失败')
    }
  } catch (e: any) {
    showToast('重启失败：' + (e?.message || e))
  } finally {
    restarting.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.field-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.field-row input {
  width: 90px;
  padding: 4px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color, #ddd);
}
.field-row .hint {
  color: var(--text-muted, #888);
  font-size: 12px;
}
.events-block {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.event-group {
  border: 1px solid var(--border-color, #eee);
  border-radius: 8px;
  padding: 12px 14px;
}
.event-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 4px;
}
.event-tag {
  font-family: 'Consolas', monospace;
  background: rgba(0, 123, 255, 0.12);
  color: #2b7de0;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}
.event-desc {
  margin: 0 0 10px;
  color: var(--text-muted, #888);
  font-size: 12px;
}
.empty-sub {
  color: var(--text-muted, #aaa);
  font-size: 12px;
  padding: 6px 0;
}
.handler-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.script-select {
  min-width: 240px;
  padding: 5px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color, #ddd);
}
.args-input {
  flex: 1;
  min-width: 260px;
  padding: 5px 8px;
  border-radius: 4px;
  border: 1px solid var(--border-color, #ddd);
}
.btn-danger {
  border-color: #e06c6c;
  color: #d85a5a;
}
.tip-box {
  margin-top: 18px;
  padding: 12px 14px;
  background: rgba(0, 0, 0, 0.03);
  border-radius: 8px;
  font-size: 12px;
  line-height: 1.8;
}
.tip-box code {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
}
.header-actions {
  display: flex;
  gap: 8px;
}
</style>
