<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { scriptApi } from '../api/script'

interface PluginInfo {
  id: string
  name: string
  description?: string
  enabled: boolean
  ui?: { title?: string; icon?: string; mount?: string }
  settings?: any[]
  error?: string
}

const router = useRouter()
const loading = ref(false)
// 扩展图标若为 http(s) 图片地址，则以 <img> 渲染；否则当文本（emoji）显示
function isHttpIcon(s: unknown): boolean {
  return typeof s === 'string' && /^https?:\/\//i.test(s)
}
const plugins = ref<PluginInfo[]>([])
const toggling = ref<string | null>(null)
const reloading = ref<string | null>(null)
const errMsg = ref('')
const toastMsg = ref('')
let toastTimer: any = null
function toast(msg: string) {
  toastMsg.value = msg
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => (toastMsg.value = ''), 2500)
}

async function load() {
  loading.value = true
  errMsg.value = ''
  try {
    const res: any = await scriptApi.listScripts(true)
    if (!res || !res.success) {
      errMsg.value = (res && res.message) || '加载失败'
      return
    }
    plugins.value = (res.scripts || []).map((s: any) => ({
      id: s.id,
      name: s.name || s.id,
      description: s.description,
      enabled: !!s.enabled,
      ui: s.ui,
      settings: s.settings || [],
      error: s.error,
    }))
  } catch (e: any) {
    errMsg.value = (e && e.response && e.response.data && e.response.data.message) || e?.message || '加载失败'
    plugins.value = []
  } finally {
    loading.value = false
  }
}

async function toggle(p: PluginInfo) {
  toggling.value = p.id
  try {
    if (p.enabled) {
      await scriptApi.disable(p.id)
      p.enabled = false
    } else {
      await scriptApi.enable(p.id)
      p.enabled = true
    }
  } catch (e) {
    // 失败保持原状
  } finally {
    toggling.value = null
  }
}

async function reloadAll() {
  try {
    await scriptApi.reload()
    toast('已重新扫描并热重载全部插件')
  } catch (e) {
    toast('重载失败：' + ((e as any)?.response?.data?.message || (e as any)?.message || '未知错误'))
  }
  await load()
}

async function reloadOne(p: PluginInfo) {
  reloading.value = p.id
  try {
    await scriptApi.reload()
    toast(`插件「${p.name}」已热重载`)
  } catch (e) {
    toast('重载失败：' + ((e as any)?.response?.data?.message || (e as any)?.message || '未知错误'))
  } finally {
    reloading.value = null
  }
}

function openSettings(p: PluginInfo) {
  router.push(`/plugins/${p.id}/settings`)
}

onMounted(load)
</script>

<template>
  <div class="plugins-page">
    <header class="page-header">
      <h1 class="page-title">扩展管理</h1>
      <p class="page-subtitle">
        管理所有已安装的外部扩展 / 第三方插件。可手动启用或停用，并为每个插件配置独立设置（由插件自身声明）。
      </p>
    </header>

    <div class="panel-toolbar">
      <button class="action-btn primary" :disabled="loading" @click="reloadAll">重新扫描</button>
      <span class="hint">扩展位于 extensions/ 目录；新增或删除目录后点此刷新。</span>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="errMsg" class="err">⚠ {{ errMsg }}</div>
    <div v-else-if="!plugins.length" class="empty">
      未发现任何扩展。请将插件包放到 extensions/&lt;id&gt;/ 并带 manifest.json。
    </div>

    <div v-else class="plugin-list">
      <div v-for="p in plugins" :key="p.id" class="plugin-card" :class="{ disabled: !p.enabled }">
        <img v-if="p.ui && isHttpIcon(p.ui.icon)" class="plugin-icon-img" :src="p.ui.icon" alt="" />
        <div class="plugin-icon" v-else-if="p.ui && p.ui.icon">{{ p.ui.icon }}</div>
        <div class="plugin-main">
          <div class="plugin-name">
            {{ p.name }}
            <span class="plugin-id">#{{ p.id }}</span>
          </div>
          <div class="plugin-desc">{{ p.description || '（无描述）' }}</div>
          <div v-if="p.error" class="plugin-err">⚠ {{ p.error }}</div>
          <div v-if="p.ui && p.ui.mount" class="plugin-tag">
            挂载方式：{{ p.ui.mount === 'floating' ? '悬浮球' : p.ui.mount === 'panel' ? '面板' : p.ui.mount }}
          </div>
        </div>
        <div class="plugin-actions">
          <label class="switch">
            <input
              type="checkbox"
              :checked="p.enabled"
              :disabled="toggling === p.id"
              @change="toggle(p)"
            />
            <span :class="p.enabled ? 'on' : ''">{{ p.enabled ? '已启用' : '已禁用' }}</span>
          </label>
          <button
            class="action-btn"
            :disabled="!p.enabled || !p.settings || !p.settings.length"
            @click="openSettings(p)"
          >
            设置
          </button>
          <button
            class="action-btn"
            :disabled="reloading === p.id"
            title="重新加载该插件代码（无需重启服务）"
            @click="reloadOne(p)"
          >
            {{ reloading === p.id ? '重载中…' : '重载' }}
          </button>
        </div>
      </div>
    </div>

    <transition name="fade">
      <div v-if="toastMsg" class="toast">{{ toastMsg }}</div>
    </transition>
  </div>
</template>

<style scoped>
.plugins-page {
  max-width: 920px;
  margin: 0 auto;
  padding: 24px 20px 60px;
}
.page-header { margin-bottom: 16px; }
.page-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
}
.page-subtitle {
  margin: 8px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
}
.panel-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 16px 0;
  flex-wrap: wrap;
}
.hint {
  font-size: 12px;
  color: var(--text-tertiary);
}
.loading, .empty {
  padding: 40px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 14px;
}
.err {
  margin: 16px 0;
  padding: 12px 16px;
  font-size: 13px;
  color: var(--danger);
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--danger) 35%, transparent);
  border-radius: 8px;
}
.plugin-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.plugin-card {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  transition: opacity .2s;
}
.plugin-card.disabled {
  opacity: .55;
}
.plugin-icon {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  background: var(--bg-surface-2);
  border-radius: 10px;
}
.plugin-icon-img {
  flex-shrink: 0;
  width: 44px;
  height: 44px;
  object-fit: contain;
  border-radius: 10px;
  background: var(--bg-surface-2);
}
.plugin-main { flex: 1; min-width: 0; }
.plugin-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.plugin-id {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-tertiary);
  background: var(--bg-surface-2);
  padding: 1px 6px;
  border-radius: 4px;
}
.plugin-desc {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.plugin-err {
  margin-top: 4px;
  font-size: 12px;
  color: var(--danger);
}
.plugin-tag {
  margin-top: 6px;
  display: inline-block;
  font-size: 11px;
  color: var(--text-tertiary);
  border: 1px solid var(--border-default);
  border-radius: 4px;
  padding: 1px 6px;
}
.plugin-actions {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 14px;
}
.switch {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-tertiary);
  cursor: pointer;
  white-space: nowrap;
}
.switch input {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
}
.switch .on {
  color: var(--accent);
}
.action-btn {
  padding: 7px 14px;
  font-size: 13px;
  color: var(--text-secondary);
  background: var(--bg-surface-2);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  cursor: pointer;
  transition: all .15s;
}
.action-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.action-btn:disabled {
  opacity: .45;
  cursor: not-allowed;
}
.toast {
  position: fixed;
  left: 50%;
  bottom: 32px;
  transform: translateX(-50%);
  background: var(--bg-surface-2);
  color: var(--text-primary);
  border: 1px solid var(--border-default);
  padding: 10px 18px;
  border-radius: 10px;
  font-size: 13px;
  box-shadow: 0 6px 24px rgba(0,0,0,.25);
  z-index: 100;
}
.fade-enter-active, .fade-leave-active { transition: opacity .2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
