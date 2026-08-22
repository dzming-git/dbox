<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { scriptApi } from '../api/script'
import DynamicForm from '../components/DynamicForm.vue'

const route = useRoute()
const router = useRouter()
const pluginId = route.params.id as string

const loading = ref(false)
const saving = ref(false)
const schema = ref<any[]>([])
const values = ref<Record<string, any>>({})
const pluginName = ref(pluginId)
const errMsg = ref('')
const savedMsg = ref('')

async function load() {
  loading.value = true
  errMsg.value = ''
  try {
    const res: any = await scriptApi.getSettings(pluginId)
    if (!res.success) {
      errMsg.value = res.message || '加载失败'
      return
    }
    pluginName.value = res.script_id || pluginId
    schema.value = res.schema || []
    values.value = { ...(res.values || {}) }
  } catch (e: any) {
    errMsg.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}

async function save() {
  saving.value = true
  savedMsg.value = ''
  errMsg.value = ''
  try {
    const res: any = await scriptApi.saveSettings(pluginId, values.value)
    if (!res.success) {
      errMsg.value = res.message || '保存失败'
      return
    }
    values.value = { ...(res.values || {}) }
    savedMsg.value = '已保存'
    setTimeout(() => (savedMsg.value = ''), 2500)
  } catch (e: any) {
    errMsg.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="ps-page">
    <header class="page-header">
      <button class="back-btn" @click="router.push('/plugins')">← 返回扩展管理</button>
      <h1 class="page-title">{{ pluginName }} · 设置</h1>
    </header>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="errMsg" class="err">{{ errMsg }}</div>

    <div v-else class="ps-body">
      <div class="ps-card">
        <DynamicForm
          :schema="schema"
          v-model="values"
        />
      </div>

      <div class="ps-footer">
        <span v-if="savedMsg" class="saved">✓ {{ savedMsg }}</span>
        <button class="action-btn primary" :disabled="saving" @click="save">
          {{ saving ? '保存中...' : '保存设置' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.ps-page {
  max-width: 760px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}
.page-header {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 18px;
}
.back-btn {
  align-self: flex-start;
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  padding: 0;
}
.back-btn:hover {
  color: var(--accent);
}
.page-title {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}
.loading, .err {
  padding: 40px;
  text-align: center;
  font-size: 14px;
}
.err { color: var(--danger); }
.ps-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 8px 20px;
}
.ps-footer {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 18px;
}
.saved {
  font-size: 13px;
  color: var(--accent);
}
.action-btn {
  padding: 9px 22px;
  font-size: 14px;
  border-radius: 8px;
  border: 1px solid var(--border-default);
  background: var(--bg-surface-2);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all .15s;
}
.action-btn.primary {
  background: var(--accent);
  color: var(--text-on-accent);
  border-color: transparent;
}
.action-btn.primary:hover:not(:disabled) {
  background: var(--accent-active);
}
.action-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}
</style>
