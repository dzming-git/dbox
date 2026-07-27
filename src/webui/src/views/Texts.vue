<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import { textApi } from '../api'
import type { TextResource } from '../types'
import WatchLaterButton from '../components/WatchLaterButton.vue'

const userStore = useUserStore()
const router = useRouter()

const texts = ref<TextResource[]>([])
const loading = ref(false)
const error = ref('')

const fetchTexts = async () => {
  loading.value = true
  error.value = ''
  try {
    const res: any = await textApi.list()
    texts.value = res.texts || []
  } catch (e: any) {
    error.value = e?.message || '加载文本失败'
  } finally {
    loading.value = false
  }
}

onMounted(fetchTexts)

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

const openEdit = (t: TextResource) => {
  editingId.value = t.id
  formTitle.value = t.presentation?.title || t.summary || ''
  formSummary.value = t.summary || ''
  formBody.value = t.body || ''
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

const removeText = async (t: TextResource) => {
  if (!confirm(`确定删除文本「${t.presentation?.title || '未命名'}」？`)) return
  try {
    await textApi.remove(t.id)
    await fetchTexts()
  } catch (e: any) {
    error.value = e?.message || '删除失败'
  }
}

const canEdit = () => userStore.user && userStore.user.role >= 2

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

    <p class="hint">文本是未来的内容管理模式，复用同一套资源索引机制（ResourceIndex + 模式归属）。可在此直接撰写，或由下载脚本以 <code>kind='text'</code> 入库。</p>

    <div v-if="loading" class="loading-container"><div class="spinner"></div><p>加载中...</p></div>
    <div v-else-if="error" class="error-box">{{ error }}</div>
    <div v-else-if="texts.length === 0" class="empty-state">
      <p>还没有文本，点击「新建文本」开始撰写。</p>
    </div>

    <div v-else class="texts-list">
      <div v-for="t in texts" :key="t.id" class="text-card" @click="openText(t)">
        <div class="text-head">
          <h3 class="text-title">{{ t.presentation?.title || '未命名文本' }}</h3>
          <span class="text-date">{{ formatDate(t.updated_at) }}</span>
          <div class="text-ops">
            <WatchLaterButton variant="bar" type="text" :id="String(t.id)" :title="t.presentation?.title || '未命名文本'" />
            <template v-if="canEdit()">
              <button class="op-btn" @click.stop="openEdit(t)">编辑</button>
              <button class="op-btn danger" @click.stop="removeText(t)">删除</button>
            </template>
          </div>
        </div>
        <p v-if="t.summary" class="text-summary">{{ t.summary }}</p>
        <p class="text-body">{{ (t.body || '').slice(0, 200) }}{{ (t.body || '').length > 200 ? '…' : '' }}</p>
      </div>
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
.section-title { font-size: 20px; font-weight: 600; color: #fff; margin: 0; }
.create-btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 16px; border: none; border-radius: 8px; background: #4CAF50; color: #fff; font-size: 14px; cursor: pointer; }
.create-btn:hover { background: #43a047; }
.hint { color: #888; font-size: 13px; margin: 8px 0 16px; line-height: 1.5; }
.hint code { background: #2a2a2a; padding: 1px 6px; border-radius: 4px; color: #9ecbff; }
.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 200px; color: #aaa; }
.spinner { width: 36px; height: 36px; border: 3px solid #333; border-top-color: #4CAF50; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { color: #ff6b6b; padding: 12px; background: #2a1a1a; border-radius: 8px; }
.empty-state { color: #666; text-align: center; padding: 60px 0; }
.texts-list { display: flex; flex-direction: column; gap: 16px; }
.text-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 14px; padding: 18px; cursor: pointer; }
.text-head { display: flex; align-items: center; gap: 12px; }
.text-title { font-size: 17px; font-weight: 600; color: #fff; margin: 0; flex: 1; }
.text-date { font-size: 12px; color: #777; }
.text-ops { display: flex; gap: 8px; }
.op-btn { padding: 5px 12px; border: 1px solid #3a3a3a; background: #252525; color: #ccc; border-radius: 6px; font-size: 13px; cursor: pointer; }
.op-btn:hover { color: #fff; }
.op-btn.danger:hover { color: #ff6b6b; border-color: #ff6b6b; }
.text-summary { color: #9ecbff; font-size: 13px; margin: 8px 0 4px; }
.text-body { color: #ccc; font-size: 14px; line-height: 1.6; white-space: pre-wrap; margin: 0; }
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 20px; }
.modal { background: #1f1f1f; border: 1px solid #333; border-radius: 14px; padding: 24px; width: 100%; max-width: 640px; max-height: 90vh; overflow-y: auto; }
.modal-title { color: #fff; margin: 0 0 16px; font-size: 18px; }
.field-label { display: block; color: #aaa; font-size: 13px; margin: 14px 0 6px; }
.text-input, .text-area { width: 100%; box-sizing: border-box; background: #141414; border: 1px solid #3a3a3a; border-radius: 8px; color: #fff; padding: 10px 12px; font-size: 14px; font-family: inherit; }
.text-area { resize: vertical; }
.text-input:focus, .text-area:focus { outline: none; border-color: #4CAF50; }
.modal-ops { display: flex; justify-content: flex-end; gap: 12px; margin-top: 20px; }
.cancel-btn { padding: 8px 18px; border: 1px solid #3a3a3a; background: #252525; color: #ccc; border-radius: 8px; cursor: pointer; }
.cancel-btn:hover { color: #fff; }
.save-btn { padding: 8px 22px; border: none; border-radius: 8px; background: #4CAF50; color: #fff; font-size: 14px; cursor: pointer; }
.save-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.save-btn:hover:not(:disabled) { background: #43a047; }
</style>
