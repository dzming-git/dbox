<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { scriptApi } from '../api/script'
import { withExtRuntime } from '../utils/extRuntime'
import {
  ensurePanel, setPanelMode, postToPanel, getPanelIframe,
  onPanelMessage, setPanelTitle,
} from '../utils/extPanelHost'

/**
 * 扩展全屏页：与小窗（悬浮面板）是**同一个 iframe 实例**的两种显示形态。
 *
 * 以前本页会新建一个 srcdoc iframe —— 那等于重建文档，面板脚本从零启动，
 * 小窗里看到的浏览位置、正在输入的文字、视频播放进度全部丢失。
 * 现在改为复用框架层 extPanelHost 的常驻面板实例，仅把形态切成 fullscreen
 * （纯 CSS，DOM 与文档都不动），因此：
 *   · 小窗 → 全屏：现场一模一样（滚动/输入/播放进度原样保留）
 *   · 全屏 → 小窗：同样原样保留
 * 本页自身不再持有 iframe，只负责路由语义、标题与形态切换。
 */
const props = defineProps<{ id?: string }>()
const route = useRoute()
const router = useRouter()

const extId = props.id || (route.params.id as string) || ''
const loading = ref(true)
const error = ref('')

let offMsg: (() => void) | null = null

async function load() {
  loading.value = true
  error.value = ''
  try {
    const exts: any = await scriptApi.listExtensions()
    const ext = (exts.extensions || []).find((e: any) => e.id === extId)
    const html = withExtRuntime((await scriptApi.getPanel(extId)) as unknown as string, extId)
    const title = ext?.ui?.title || extId
    // 已存在实例则只更新（不重建文档）；不存在则创建并立即切到 fullscreen
    const existed = !!getPanelIframe(extId)
    ensurePanel(extId, {
      html,
      sandbox: ext?.ui?.sandbox,
      title,
      standaloneRoute: ext?.ui?.standalone_route,
    })
    if (!existed) setPanelTitle(extId, title)
    setPanelMode(extId, 'fullscreen')
    pushRuntime()
  } catch (e: any) {
    error.value = '面板加载失败：' + (e?.message || e)
  } finally {
    loading.value = false
  }
}

function readToken(): string {
  return localStorage.getItem('token')
    || localStorage.getItem('access_token')
    || sessionStorage.getItem('token')
    || ''
}

/** 向面板补注入 token/模式/路由 query（每次都读最新 token，避免 401） */
function pushRuntime() {
  if (!getPanelIframe(extId)) return
  const fresh = readToken()
  if (fresh) postToPanel(extId, { type: 'DBOX_TOKEN', token: fresh })
  postToPanel(extId, { type: 'DBOX_MODE', fullscreen: true })
  if (route.query && Object.keys(route.query).length) {
    postToPanel(extId, { type: 'DBOX_ROUTE', query: { ...route.query } })
  }
}

function handleMsg(data: any, id: string) {
  if (!data || id !== extId) return
  if (data.type === 'DBOX_REQUEST_TOKEN') pushRuntime()
  // 面板内跳转：全屏页本身就是「界面」，直接路由跳转即可（面板实例不动）。
  if (data.type === 'DBOX_NAVIGATE' && data.path) {
    if (data.path === '__back__') {
      if (route.fullPath !== '/' + extId) router.push('/' + extId)
    } else {
      router.push(data.path)
    }
  }
}

function goBack() {
  // 全屏页左上角：回到进入全屏页之前的页面（优先 history back，无历史则回首页）。
  // 面板实例保留（切为隐藏），下次再打开仍是离开前的现场。
  if (window.history.length > 1) router.back()
  else router.push('/')
}

// 面板标题栏「收起」按钮（extPanelHost 内建）在全屏态触发：离开全屏路由页回到上一页
function onExitFullscreen(e: Event) {
  const d = (e as CustomEvent).detail || {}
  if (d.extId && d.extId !== extId) return
  goBack()
}

onMounted(async () => {
  offMsg = onPanelMessage(handleMsg)
  window.addEventListener('dbox-ext-exit-fullscreen', onExitFullscreen as EventListener)
  await load()
})

onUnmounted(() => {
  if (offMsg) { offMsg(); offMsg = null }
  window.removeEventListener('dbox-ext-exit-fullscreen', onExitFullscreen as EventListener)
  // 离开全屏页：把面板收起（隐藏而非销毁），保留其全部状态
  if (extId && getPanelIframe(extId)) setPanelMode(extId, 'hidden')
})
</script>

<template>
  <!--
    面板 iframe 由 extPanelHost 常驻在 body 下并以 CSS 铺满视口（fullscreen 形态），
    因此本页不需要也不能再渲染一个 iframe，否则就是重建文档、丢失状态。
    这里只保留一个轻量的返回条与加载/错误提示。
  -->
  <div class="ext-standalone-page">
    <div class="ext-std-header">
      <button class="ext-std-back" @click="goBack">← 首页</button>
      <span class="ext-std-title">{{ extId }}</span>
    </div>
    <div v-if="loading" class="ext-std-tip">加载中…</div>
    <div v-else-if="error" class="ext-std-tip ext-std-err">{{ error }}</div>
  </div>
</template>

<style scoped>
.ext-standalone-page {
  position: fixed;
  inset: 0;
  z-index: 2900;
  display: flex;
  flex-direction: column;
  background: #f7f8fa;
}
.ext-std-header {
  display: flex;
  align-items: center;
  gap: 12px;
  height: 44px;
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
.ext-std-tip {
  flex: 1;
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
