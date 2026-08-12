<script setup lang="ts">
import { ref, onMounted, watch, onActivated, onDeactivated } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import { textApi } from '../api'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import type { TextResource } from '../types'
import PlainListRow from '../components/PlainListRow.vue'

const userStore = useUserStore()
const router = useRouter()

const texts = ref<TextResource[]>([])
const loading = ref(false)
const error = ref('')

const searchQuery = ref('')

const fetchTexts = async () => {
  loading.value = true
  error.value = ''
  try {
    const params: any = {}
    if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
    const res: any = await textApi.list(params)
    texts.value = res.texts || []
  } catch (e: any) {
    error.value = e?.message || '加载文本失败'
  } finally {
    loading.value = false
  }
}

onMounted(fetchTexts)

// 顶部下拉刷新：仅作为独立路由（/texts）时注册，嵌入首页时不接管手势
const route = useRoute()
const ptr = usePullToRefresh()
function registerPtr() {
  if (route.name !== 'Texts') return
  ptr.setHandler(fetchTexts)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())
// 供首页 text 标签调用
defineExpose({ reload: fetchTexts })

let searchTimer: number | null = null
watch(searchQuery, () => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => fetchTexts(), 500)
})

// ============ 新建 / 编辑 ============
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const formTitle = ref('')
const formSummary = ref('')
const formBody = ref('')
const saving = ref(false)

const openCreate = () => {
  editingId.value = null
  formTitle.value = ''
  formSummary.value = ''
  formBody.value = ''
  dialogVisible.value = true
}

const save = async () => {
  if (saving.value) return
  saving.value = true
  try {
    const data = { title: formTitle.value, summary: formSummary.value, body: formBody.value }
    if (editingId.value) {
      await textApi.update(editingId.value, data)
    } else {
      await textApi.create(data)
    }
    dialogVisible.value = false
    await fetchTexts()
  } catch (e: any) {
    error.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const openText = (t: TextResource) => {
  router.push(`/text/${t.id}`)
}

const formatDate = (s?: string) => {
  if (!s) return ''
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN')
}
</script>

<template>
  <div class="texts-container">
    <div class="texts-header">
      <h2 class="section-title">文本</h2>
      <button class="create-btn" @click="openCreate">新建文本</button>
    </div>
    <div class="search-box">
      <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
      </svg>
      <input v-model="searchQuery" type="text" placeholder="搜索文本标题或内容..." class="search-input" />
    </div>

    <p class="hint">文本是未来的内容管理模式，复用同一套资源索引机制（ResourceIndex + 模式归属）。可在此直接撰写，或由下载脚本以 <code>kind='text'</code> 入库。</p>

    <div v-if="loading" class="loading-container"><div class="spinner"></div><p>加载中...</p></div>
    <div v-else-if="error" class="error-box">{{ error }}</div>
    <div v-else-if="texts.length === 0" class="empty-state">
      <p>还没有文本，点击「新建文本」开始撰写。</p>
    </div>

    <div v-else class="texts-list">
      <PlainListRow
        v-for="t in texts"
        :key="t.id"
        type="text"
        :item="t"
        :title="t.presentation?.title || '未命名文本'"
        :meta="[formatDate(t.updated_at)]"
        @click="openText"
      >
        <p v-if="t.summary" class="text-summary">{{ t.summary }}</p>
        <p class="text-body">{{ (t.body || '').slice(0, 200) }}{{ (t.body || '').length > 200 ? '…' : '' }}</p>
      </PlainListRow>
    </div>

    <div v-if="dialogVisible" class="modal-mask" @click.self="dialogVisible = false">
      <div class="modal">
        <h3 class="modal-title">{{ editingId ? '编辑文本' : '新建文本' }}</h3>
        <label class="field-label">标题</label>
        <input class="text-input" v-model="formTitle" placeholder="标题" />
        <label class="field-label">摘要</label>
        <input class="text-input" v-model="formSummary" placeholder="一句话摘要（可选）" />
        <label class="field-label">正文</label>
        <textarea class="text-area" v-model="formBody" rows="10" placeholder="写点什么..."></textarea>
        <div class="modal-ops">
          <button class="cancel-btn" @click="dialogVisible = false">取消</button>
          <button class="save-btn" :disabled="saving" @click="save">{{ saving ? '保存中...' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.texts-container { padding: 20px; max-width: 1000px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.texts-header { display: flex; align-items: center; justify-content: space-between; }
.search-box { display: flex; align-items: center; gap: 8px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 8px; padding: 8px 12px; margin: 12px 0 16px; }
.search-icon { color: var(--text-tertiary); flex-shrink: 0; }
.search-input { background: transparent; border: none; color: var(--text-primary); font-size: 14px; outline: none; width: 100%; }
.search-input::placeholder { color: var(--text-tertiary); }
.section-title { font-size: 20px; font-weight: 600; color: var(--text-primary); margin: 0; }
.create-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border: none; border-radius: 8px; background: var(--accent); color: var(--text-on-accent); font-size: 14px; cursor: pointer; }
.create-btn:hover { background: var(--accent-active); }
.hint { color: var(--text-secondary); font-size: 13px; margin: 8px 0 16px; line-height: 1.5; }
.hint code { background: var(--bg-surface-hover); padding: 1px 6px; border-radius: 4px; color: var(--text-secondary); }
.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 200px; color: var(--text-secondary); }
.spinner { width: 36px; height: 36px; border: 3px solid var(--border-default); border-top-color: #4CAF50; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { color: var(--danger); padding: 12px; background: var(--danger-soft); border-radius: 8px; }
.empty-state { color: var(--text-tertiary); text-align: center; padding: 60px 0; }
.texts-list { display: flex; flex-direction: column; gap: 16px; }
.op-btn { padding: 5px 12px; border: 1px solid var(--border-default); background: var(--bg-surface-hover); color: var(--text-secondary); border-radius: 6px; font-size: 13px; cursor: pointer; }
.op-btn:hover { color: var(--accent); }
.op-btn.danger:hover { color: var(--danger); border-color: var(--danger); }
.text-summary { color: var(--text-secondary); font-size: 13px; margin: 8px 0 4px; }
.text-body { color: var(--text-secondary); font-size: 14px; line-height: 1.6; white-space: pre-wrap; margin: 0; }
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 20px; }
.modal { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 14px; padding: 24px; width: 100%; max-width: 640px; max-height: 90vh; overflow-y: auto; }
.modal-title { color: var(--text-primary); margin: 0 0 16px; font-size: 18px; }
.field-label { display: block; color: var(--text-secondary); font-size: 13px; margin: 14px 0 6px; }
.text-input, .text-area { width: 100%; box-sizing: border-box; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 8px; color: var(--text-primary); padding: 10px 12px; font-size: 14px; font-family: inherit; }
.text-area { resize: vertical; }
.text-input:focus, .text-area:focus { outline: none; border-color: #4CAF50; }
.modal-ops { display: flex; justify-content: flex-end; gap: 12px; margin-top: 20px; }
.cancel-btn { padding: 8px 18px; border: 1px solid var(--border-default); background: var(--bg-surface-hover); color: var(--text-secondary); border-radius: 8px; cursor: pointer; }
.cancel-btn:hover { color: var(--accent); }
.save-btn { padding: 8px 22px; border: none; border-radius: 8px; background: #4CAF50; color: var(--text-on-accent); font-size: 14px; cursor: pointer; }
.save-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.save-btn:hover:not(:disabled) { background: #43a047; }
</style>