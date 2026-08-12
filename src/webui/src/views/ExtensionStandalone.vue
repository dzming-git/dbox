<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { scriptApi } from '../api/script'

// 拓展插件式全屏页：按扩展 id 复用其 panel.html（与悬浮面板同一份 UI 资源），
// 仅在「独享一个界面」的全屏 iframe 中渲染。任意声明了 ui.entry 的扩展都可用此页，
// 不限于 AI 助手——AI 助手通过 /ai-chat 路由（props.id=ai_chat）独享该界面。
const props = defineProps<{ id?: string }>()
const route = useRoute()
const router = useRouter()

const extId = props.id || (route.params.id as string) || 'ai_chat'
const title = ref('AI 助手')
const html = ref('')
const loading = ref(true)
const error = ref('')
const iframeRef = ref<HTMLIFrameElement | null>(null)
let token = ''

async function load() {
  loading.value = true
  error.value = ''
  try {
    // 扩展元信息取标题（与悬浮面板同一来源）；失败不影响面板加载
    try {
      const exts: any = await scriptApi.listExtensions()
      const ext = (exts.extensions || []).find((e: any) => e.id === extId)
      if (ext?.ui?.title) title.value = ext.ui.title
    } catch (e) { /* 标题仅是展示，忽略 */ }
    // getPanel 经响应拦截器已剥为 HTML 文本
    html.value = (await scriptApi.getPanel(extId)) as unknown as string
  } catch (e: any) {
    error.value = '面板加载失败：' + (e?.message || e)
  } finally {
    loading.value = false
  }
}

function loadToken() {
  // 与悬浮面板宿主（ExtensionHost）同一来源：注入给 iframe，供其调用后端 / ui-proxy。
  // 即便面板自身已可直读 localStorage，这里仍补齐，避免任何路径下 token 缺失触发 401。
  token = localStorage.getItem('token') || localStorage.getItem('access_token') || sessionStorage.getItem('token') || ''
}

// 通知面板：进入全屏独立模式（隐藏「全屏对话」按钮），并补注入 token。
function notifyIframe() {
  const w = iframeRef.value?.contentWindow
  if (!w) return
  w.postMessage({ type: 'DBOX_MODE', fullscreen: true }, '*')
  if (token) w.postMessage({ type: 'DBOX_TOKEN', token }, '*')
}

function onMessage(e: MessageEvent) {
  if (!e.data) return
  // 面板挂载后向父页请求 token：补注入（面板自身也能直读 localStorage，双保险）。
  if (e.data.type === 'DBOX_REQUEST_TOKEN') {
    notifyIframe()
    return
  }
  // 面板内跳转（如点击资源引用卡片）：全屏页本身即「界面」，无需收起面板，
  // 直接路由跳转即可；'__back__' 语义交给「返回」按钮处理，这里不处理。
  if (e.data.type === 'DBOX_NAVIGATE' && e.data.path && e.data.path !== '__back__') {
    router.push(e.data.path)
  }
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/')
}

// iframe 加载完成后通知面板：当前处于全屏独立模式，便于其隐藏「全屏对话」按钮。
function onIframeLoad() {
  notifyIframe()
}

onMounted(() => {
  loadToken()
  // 真全屏：隐藏全局导航，让扩展界面独享整个视口（组件卸载时移除）
  document.body.classList.add('ext-standalone')
  window.addEventListener('message', onMessage)
  load()
})
onUnmounted(() => {
  window.removeEventListener('message', onMessage)
  document.body.classList.remove('ext-standalone')
})
</script>

<template>
  <div class="ext-standalone-page">
    <div class="ext-std-header">
      <button class="ext-std-back" @click="goBack">← 返回</button>
      <span class="ext-std-title">{{ title }}</span>
    </div>
    <div class="ext-std-body">
      <div v-if="loading" class="ext-std-tip">加载中…</div>
      <div v-else-if="error" class="ext-std-tip ext-std-err">{{ error }}</div>
      <iframe
        v-else
        ref="iframeRef"
        class="ext-std-frame"
        sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
        :srcdoc="html"
        @load="onIframeLoad"
      ></iframe>
    </div>
  </div>
</template>

<style scoped>
.ext-standalone-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f7f8fa;
}
.ext-std-header {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 48px;
  padding: 0 12px;
  background: #fff;
  border-bottom: 1px solid #e3e6eb;
  flex-shrink: 0;
}
.ext-std-back {
  background: none;
  border: 1px solid #d0d4dc;
  color: #555;
  border-radius: 6px;
  font-size: 13px;
  padding: 4px 12px;
  cursor: pointer;
}
.ext-std-back:hover {
  color: #4f8cff;
  border-color: #4f8cff;
}
.ext-std-title {
  font-weight: 600;
  font-size: 15px;
  color: #1f2329;
}
.ext-std-body {
  flex: 1;
  min-height: 0;
  position: relative;
}
.ext-std-frame {
  width: 100%;
  height: 100%;
  border: none;
  background: #f7f8fa;
}
.ext-std-tip {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #888;
  font-size: 14px;
}
.ext-std-err {
  color: #d33;
}
</style>
