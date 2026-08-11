<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { scriptApi, type ScriptInfo } from '../api/script'

interface ExtensionUI {
  mount: string
  title: string
  icon: string
  entry?: string
  needs_credential: boolean
  sandbox: string
}

interface Extension {
  id: string
  name: string
  ui: ExtensionUI
}

const extensions = ref<Extension[]>([])
const panelHtml = ref<Record<string, string>>({})
const openId = ref<string | null>(null)
const token = ref('')

async function loadToken() {
  // 从 localStorage 读取当前管理员的 access token（与 axios 拦截器一致）
  const raw = localStorage.getItem('token') || localStorage.getItem('access_token') || sessionStorage.getItem('token')
  token.value = raw || ''
}

async function loadExtensions() {
  try {
    const res: any = await scriptApi.listExtensions()
    if (!res.success) return
    extensions.value = res.extensions || []
  } catch (e) {
    extensions.value = []
  }
}

async function toggle(id: string) {
  if (openId.value === id) {
    openId.value = null
    return
  }
  openId.value = id
  const ext = extensions.value.find((e) => e.id === id)
  if (!ext?.ui.entry) return
  if (!panelHtml.value[id]) {
    try {
      const res: any = await scriptApi.getPanel(id)
      panelHtml.value[id] = res
    } catch (e) {
      panelHtml.value[id] = '<p style="color:#f66;padding:12px">面板加载失败</p>'
    }
  }
  // token 就绪后通过 postMessage 注入给 iframe（供其调用后端 / ui-proxy）
  await nextTick()
  pushToken(id)
}

function pushToken(id: string) {
  const iframe = document.getElementById(`ext-frame-${id}`) as HTMLIFrameElement | null
  if (iframe?.contentWindow) {
    iframe.contentWindow.postMessage({ type: 'DBOX_TOKEN', token: token.value }, '*')
  }
}

function onMessage(e: MessageEvent) {
  // iframe 反向请求 token（例如刚挂载时）
  if (e.data?.type === 'DBOX_REQUEST_TOKEN') {
    const id = e.data.extId
    if (id) pushToken(id)
  }
}

onMounted(async () => {
  await loadToken()
  await loadExtensions()
  window.addEventListener('message', onMessage)
})

watch(openId, (id) => {
  if (id) pushToken(id)
})
</script>

<template>
  <div class="ext-host">
    <template v-for="ext in extensions" :key="ext.id">
      <!-- 悬浮球入口 -->
      <div
        v-if="ext.ui.mount === 'floating'"
        class="ext-fab"
        :title="ext.ui.title"
        @click="toggle(ext.id)"
      >
        <span class="ext-fab-icon">{{ ext.ui.icon }}</span>
      </div>

      <!-- 展开的面板 -->
      <div
        v-if="ext.ui.mount === 'floating' && openId === ext.id"
        class="ext-panel"
      >
        <div class="ext-panel-header">
          <span>{{ ext.ui.title }}</span>
          <button class="ext-close" @click="openId = null">×</button>
        </div>
        <iframe
          :id="`ext-frame-${ext.id}`"
          class="ext-frame"
          :sandbox="ext.ui.sandbox"
          :srcdoc="panelHtml[ext.id] || ''"
        ></iframe>
      </div>

      <!-- 固定侧边面板 -->
      <div
        v-if="ext.ui.mount === 'panel' && openId === ext.id"
        class="ext-side-panel"
      >
        <iframe
          :id="`ext-frame-${ext.id}`"
          class="ext-frame"
          :sandbox="ext.ui.sandbox"
          :srcdoc="panelHtml[ext.id] || ''"
        ></iframe>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ext-fab {
  position: fixed;
  right: 20px;
  bottom: 24px;
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: var(--accent, #4f8cff);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  z-index: 9000;
  font-size: 22px;
  transition: transform 0.15s;
}
.ext-fab:hover {
  transform: scale(1.08);
}
.ext-panel {
  position: fixed;
  right: 20px;
  bottom: 84px;
  width: 360px;
  height: 480px;
  max-width: 92vw;
  max-height: 80vh;
  background: var(--bg-elevated, #1e1e22);
  border: 1px solid var(--border-default, #333);
  border-radius: 12px;
  z-index: 9001;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
.ext-panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-surface-2, #2a2a30);
  color: var(--text-primary, #eee);
  font-size: 14px;
  font-weight: 600;
}
.ext-close {
  background: none;
  border: none;
  color: var(--text-secondary, #aaa);
  font-size: 20px;
  cursor: pointer;
  line-height: 1;
}
.ext-frame {
  flex: 1;
  width: 100%;
  border: none;
  background: #fff;
}
.ext-side-panel {
  position: fixed;
  right: 0;
  top: 0;
  bottom: 0;
  width: 380px;
  max-width: 92vw;
  background: var(--bg-elevated, #1e1e22);
  z-index: 9002;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.4);
}
</style>
