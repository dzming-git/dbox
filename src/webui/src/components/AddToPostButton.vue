<template>
  <div class="add-to-post-wrap">
    <button
      ref="triggerRef"
      class="atp-trigger"
      :class="{ active: open, done: justAdded }"
      :title="justAdded ? '已加入帖子' : '把这条资源引用到帖子'"
      @click="toggle"
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M12 5v14M5 12h14" />
      </svg>
      <span>{{ justAdded ? '已加入' : '引用到帖子' }}</span>
    </button>

    <div v-if="open" class="atp-mask" @click="close"></div>
    <div v-if="open" class="atp-panel" :style="panelStyle">
      <div class="atp-head">
        <span>引用到帖子</span>
        <button class="atp-close" @click="close">✕</button>
      </div>

      <div v-if="loading" class="atp-tip">加载中…</div>
      <div v-else class="atp-body">
        <div class="atp-new">
          <input
            v-model="newTitle"
            class="atp-input"
            placeholder="新建一篇帖子（输入标题）"
            @keyup.enter="createAndAdd"
          />
          <button class="atp-btn primary" :disabled="!newTitle.trim() || busy" @click="createAndAdd">
            新建并加入
          </button>
        </div>
        <div class="atp-sep"><span>或加入已有帖子</span></div>
        <div v-if="!posts.length" class="atp-tip">还没有帖子，先在上面新建一篇</div>
        <div v-else class="atp-list">
          <button
            v-for="p in posts"
            :key="p.id"
            class="atp-item"
            :class="{ added: addedIds.includes(p.id) }"
            :disabled="busy"
            @click="addTo(p)"
          >
            <span class="atp-item-name">{{ p.title || '(无标题)' }}</span>
            <span v-if="p.status === 'draft'" class="atp-draft">草稿</span>
            <span v-if="addedIds.includes(p.id)" class="atp-ok">✓ 已加入</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { useRouter } from 'vue-router'
import { postApi } from '../api'

const props = defineProps<{
  /** 资源索引 ID：帖子引用的就是这个 */
  resourceIndexId: number | null | undefined
}>()

const router = useRouter()
const open = ref(false)
const loading = ref(false)
const busy = ref(false)
const posts = ref<any[]>([])
const addedIds = ref<number[]>([])
const newTitle = ref('')
const justAdded = ref(false)
const triggerRef = ref<HTMLElement | null>(null)

const panelStyle = computed<Record<string, string>>(() => {
  const el = triggerRef.value
  if (!el) return {}
  const r = el.getBoundingClientRect()
  const w = 280
  let left = r.left
  if (left + w > window.innerWidth - 8) left = window.innerWidth - w - 8
  return { top: `${Math.min(r.bottom + 6, window.innerHeight - 320)}px`, left: `${Math.max(8, left)}px` }
})

async function load() {
  loading.value = true
  try {
    // status=all + mine：草稿也能往里加（草稿本来就是"攒素材"用的）
    const r: any = await postApi.list({ status: 'all', mine: 1 })
    posts.value = r?.posts || []
  } catch {
    posts.value = []
  } finally {
    loading.value = false
  }
}

function toggle() {
  open.value = !open.value
  if (open.value && !posts.length) load()
}

function close() {
  open.value = false
}
function onDocClick(e: MouseEvent) {
  if (!open.value) return
  if (!(e.target as HTMLElement)?.closest?.('.add-to-post-wrap')) close()
}
function onEsc(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
}
document.addEventListener('click', onDocClick)
document.addEventListener('keydown', onEsc)
onBeforeUnmount(() => {
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onEsc)
})

function flashDone() {
  justAdded.value = true
  setTimeout(() => (justAdded.value = false), 2000)
}

async function createAndAdd() {
  const name = newTitle.value.trim()
  if (!name || !props.resourceIndexId) return
  busy.value = true
  try {
    // 带引用直接建：后端会在 content 为空时按 refs 写入
    const r: any = await postApi.create({
      title: name,
      content: '',
      refs: [{ resource_index_id: props.resourceIndexId }],
    })
    const pid = r?.id
    if (pid) {
      posts.value.unshift(r)
      addedIds.value.push(pid)
      flashDone()
      newTitle.value = ''
      if (confirm(`已加入新帖子「${name}」。现在去编辑它吗？`)) {
        router.push(`/post/${pid}`)
      }
    }
  } catch (e: any) {
    alert(e?.response?.data?.error || e?.message || '创建失败')
  } finally {
    busy.value = false
  }
}

async function addTo(p: any) {
  if (!props.resourceIndexId || addedIds.value.includes(p.id)) return
  busy.value = true
  try {
    await postApi.addRef(p.id, { resource_index_id: props.resourceIndexId })
    addedIds.value.push(p.id)
    flashDone()
    if (confirm(`已加入「${p.title || '帖子'}」。现在去看看吗？`)) {
      router.push(`/post/${p.id}`)
    }
  } catch (e: any) {
    const msg = e?.response?.data?.error || e?.message || '加入失败'
    // 已经在帖子里不算错误，标成已加入即可
    if (/已存在|duplicate/i.test(msg)) {
      addedIds.value.push(p.id)
      flashDone()
    } else {
      alert(msg)
    }
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.add-to-post-wrap {
  position: relative;
  display: inline-flex;
}
.atp-trigger {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  transition: color 0.18s ease, border-color 0.18s ease, background 0.18s ease;
}
.atp-trigger:hover {
  color: var(--text-primary);
  border-color: var(--accent-border);
}
.atp-trigger.active {
  color: var(--accent);
  border-color: var(--accent);
}
.atp-trigger.done {
  color: var(--success);
  border-color: var(--success);
}
.atp-mask {
  position: fixed;
  inset: 0;
  z-index: 60;
}
.atp-panel {
  position: fixed;
  z-index: 61;
  width: 280px;
  max-height: 60vh;
  overflow-y: auto;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  box-shadow: var(--shadow-md);
  padding: 10px 12px 12px;
}
.atp-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.atp-close {
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  font-size: 13px;
}
.atp-new {
  display: flex;
  gap: 6px;
}
.atp-input {
  flex: 1;
  min-width: 0;
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 13px;
}
.atp-input:focus {
  outline: none;
  border-color: var(--accent-border);
}
.atp-btn {
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
  border: 1px solid var(--border-default);
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  white-space: nowrap;
}
.atp-btn.primary {
  background: var(--accent);
  color: var(--text-on-accent);
  border-color: transparent;
}
.atp-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.atp-sep {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0 6px;
  color: var(--text-tertiary);
  font-size: 11px;
}
.atp-sep::before,
.atp-sep::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-subtle);
}
.atp-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.atp-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 7px 10px;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}
.atp-item:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}
.atp-item.added {
  color: var(--success);
}
.atp-item-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.atp-draft {
  font-size: 11px;
  color: var(--warning);
  border: 1px solid var(--warning-soft);
  border-radius: 999px;
  padding: 0 6px;
}
.atp-ok {
  font-size: 11px;
}
.atp-tip {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 8px 2px;
}
</style>
