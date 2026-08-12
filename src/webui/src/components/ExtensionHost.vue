<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { scriptApi, type ScriptInfo } from '../api/script'

const router = useRouter()
const route = useRoute()

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
// 面板收起后暂存各扩展未发送的输入草稿，重新展开时回填（避免误触收起丢失已输入内容）
const drafts = ref<Record<string, string>>({})
// AI 助手忙碌态：气泡入口的灵动反馈。由宿主侧轻量轮询后端任务接口得到「是否有正在处理/
// 排队的 AI 任务」，与面板 iframe 生命周期解耦——即使面板收起（iframe 被卸载），
// 气泡也能在 AI 后台工作时持续显示忙碌动画。
const busyMap = ref<Record<string, boolean>>({})
function fabBusy(id: string) { return !!busyMap.value[id] }
// AI 助手未读提醒：面板收起期间若有任务产出结果（history 顶部变化），累计未读数，
// 悬浮气泡入口显示角标，避免用户忘记曾布置过任务。打开面板即清空未读。
const unreadMap = ref<Record<string, number>>({})
function fabUnread(id: string) { return unreadMap.value[id] || 0 }
// 用户「正在看 AI 对话」的两种情形：悬浮面板展开 / 全屏对话页（/ai-chat 路由）。
// 两者都算已查看，未读角标不应增长也不应残留。
const aiChatViewing = computed(() => openId.value === 'ai_chat' || route.path === '/ai-chat')
let lastHistoryTop: string | null = null  // 上一次轮询到的最近已完成任务 id
let seeded = false                         // 首次轮询仅建立基线，不误报未读
let busyTimer: any = null
async function pollAiBusy() {
  const hasAi = extensions.value.some((e) => e.id === 'ai_chat' && e.ui?.mount === 'floating')
  if (!hasAi) { busyMap.value = {}; unreadMap.value = {}; lastHistoryTop = null; seeded = false; return }
  try {
    const headers: Record<string, string> = {}
    if (token.value) headers['Authorization'] = 'Bearer ' + token.value
    const resp = await fetch('/api/ai-chat/tasks?limit=1', { headers })
    if (!resp.ok) return
    const d: any = await resp.json()
    busyMap.value = { ai_chat: !!(d.active) || (d.pending && d.pending.length > 0) }
    // 完成态检测：最新一条已完成对话（history 顶部）发生变化 = 有任务刚产出结果。
    // 若此时面板处于收起状态（用户没在看），记为一条未读；首次轮询只建基线不计数。
    const topId = d.history && d.history.length ? d.history[0].id : null
    if (topId && topId !== lastHistoryTop) {
      // 悬浮面板未展开「且」未处于全屏对话页时，才累计未读；正在看则不算未读
      if (seeded && !aiChatViewing.value) {
        unreadMap.value = { ...unreadMap.value, ai_chat: (unreadMap.value.ai_chat || 0) + 1 }
      }
      lastHistoryTop = topId
    }
    seeded = true
  } catch (e) { /* 网络抖动忽略，下个周期重试 */ }
}

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
    iframe.contentWindow.postMessage({ type: 'DBOX_DRAFT', text: drafts.value[id] || '' }, '*')
  }
}

function onMessage(e: MessageEvent) {
  // iframe 反向请求 token（例如刚挂载时）
  if (e.data?.type === 'DBOX_REQUEST_TOKEN') {
    const id = e.data.extId
    if (id) pushToken(id)
  }
  // iframe 同步未发送的输入内容，供收起后再展开时恢复
  if (e.data?.type === 'DBOX_DRAFT_SAVE') {
    const id = e.data.extId
    if (id) drafts.value[id] = typeof e.data.text === 'string' ? e.data.text : ''
  }
  // iframe 请求父页面跳转（如 AI 助手面板中点击反馈单引用，跳转到反馈中心详情）。
  // 任何聊天框内的跳转都遵循同一逻辑：跳转后自动收起聊天窗口，避免遮挡目标页。
  if (e.data?.type === 'DBOX_NAVIGATE' && e.data.path) {
    // '__back__' 为全屏页「退出全屏」语义：返回进入全屏前的页面（悬浮面板所在页）
    if (e.data.path === '__back__') router.back()
    else router.push(e.data.path)
    // 除非显式声明 keepPanel，否则跳转后收起面板（统一逻辑，供未来各类资源跳转复用）
    if (e.data.keepPanel !== true) {
      openId.value = null
    }
  }
}

// 点击面板以外（遮罩层）时自动收起；遮罩同时拦截点击，避免误触到后面的页面内容
function closePanel() {
  openId.value = null
}

onMounted(async () => {
  await loadToken()
  await loadExtensions()
  window.addEventListener('message', onMessage)
  syncScrollLock()
  // 轻量轮询 AI 忙碌态以驱动气泡入口动画（即使面板收起也持续生效）
  pollAiBusy()
  busyTimer = setInterval(pollAiBusy, 2000)
})

onUnmounted(() => {
  window.removeEventListener('message', onMessage)
  if (busyTimer) clearInterval(busyTimer)
  // 组件卸载（理论上为全局常驻）时释放背景滚动锁，避免残留锁定
  document.body.classList.remove('ext-no-scroll')
})

// 呼出悬浮面板（带遮罩）时锁定背景滚动，避免面板后的页面跟随鼠标滚轮/触摸上下滑动
function syncScrollLock() {
  const ext = openId.value ? extensions.value.find((e) => e.id === openId.value) : null
  if (openId.value && ext?.ui?.mount === 'floating') {
    document.body.classList.add('ext-no-scroll')
  } else {
    document.body.classList.remove('ext-no-scroll')
  }
}

watch(openId, (id) => {
  if (id) {
    pushToken(id)
    // 打开面板即视为已查看：清空该扩展未读角标
    if (unreadMap.value[id]) unreadMap.value = { ...unreadMap.value, [id]: 0 }
  }
  syncScrollLock()
})

// 进入全屏对话页（/ai-chat）即视为已查看：清空未读角标，避免退出后仍提示未读
watch(aiChatViewing, (v) => {
  if (v && unreadMap.value['ai_chat']) {
    unreadMap.value = { ...unreadMap.value, ai_chat: 0 }
  }
})
</script>

<template>
  <div class="ext-host">
    <!-- 展开时的遮罩：拦截对页面内容的点击，点击遮罩收起面板 -->
    <div v-if="openId" class="ext-mask" @click="closePanel"></div>

    <template v-for="ext in extensions" :key="ext.id">
      <!-- 悬浮球入口 -->
      <div
        v-if="ext.ui.mount === 'floating' && !(ext.id === 'ai_chat' && route.path === '/ai-chat')"
        class="ext-fab"
        :class="{ 'is-open': openId === ext.id, 'is-busy': fabBusy(ext.id) }"
        :title="ext.ui.title"
        @click="toggle(ext.id)"
      >
        <span class="ext-fab-icon">{{ ext.ui.icon }}</span>
        <span v-if="fabUnread(ext.id)" class="ext-fab-badge">{{ fabUnread(ext.id) > 99 ? '99+' : fabUnread(ext.id) }}</span>
        <span class="ext-fab-label">{{ fabBusy(ext.id) ? 'AI 正在思考…' : ext.ui.title }}</span>
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
.ext-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.12);
  z-index: 8999;
}
/* 悬浮入口：始终为圆形按钮，半透明低遮挡；悬停/展开时仅放大并提升不透明度，
   不展开成椭圆。文字标签只在悬停时以左侧气泡形式提示，避免遮挡页面 */
.ext-fab {
  position: fixed;
  right: 16px;
  bottom: 18px;
  height: 44px;
  width: 44px;
  padding: 0;
  border-radius: 50%;
  background: var(--accent, #4f8cff);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18);
  z-index: 9000;
  opacity: 0.82;
  overflow: visible;
  transition: opacity 0.15s, transform 0.15s, box-shadow 0.15s;
}
.ext-fab:hover,
.ext-fab.is-open {
  opacity: 1;
  transform: scale(1.08);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
}
.ext-fab-icon {
  font-size: 20px;
  line-height: 1;
}
/* 未读角标：面板收起期间有任务产出结果时，悬浮入口右上角显示红点计数，
   提醒用户曾布置过任务；带轻微脉冲以吸引注意，但足够克制不打扰。 */
.ext-fab-badge {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #f5455c;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
  border: 2px solid var(--bg-elevated, #1e1e22);
  box-sizing: content-box;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3);
  pointer-events: none;
  animation: fab-badge-pulse 1.8s ease-in-out infinite;
}
@keyframes fab-badge-pulse {
  0%, 100% { transform: scale(1); }
  50% { transform: scale(1.12); }
}
/* AI 忙碌态：外部气泡入口的灵动反馈——旋转光环 + 呼吸光晕 + 图标轻浮，
   与面板内 AI 头像的「旋转光环」视觉语言保持一致；空闲/错误态完全静态，不打扰。 */
.ext-fab.is-busy {
  animation: fab-breathe 1.8s ease-in-out infinite;
}
.ext-fab.is-busy::after {
  content: '';
  position: absolute;
  inset: -4px;
  border-radius: 50%;
  background: conic-gradient(from 0deg, rgba(79, 140, 255, 0) 0deg, rgba(79, 140, 255, 0) 220deg, var(--accent, #4f8cff) 360deg);
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px));
          mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px));
  animation: fab-spin 1.1s linear infinite;
  pointer-events: none;
}
.ext-fab.is-busy .ext-fab-icon {
  animation: fab-bob 1.8s ease-in-out infinite;
}
@keyframes fab-spin { to { transform: rotate(360deg); } }
@keyframes fab-breathe {
  0%, 100% { box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18); }
  50% { box-shadow: 0 0 0 6px rgba(79, 140, 255, 0.16), 0 6px 18px rgba(79, 140, 255, 0.5); }
}
@keyframes fab-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-2px); }
}
@media (prefers-reduced-motion: reduce) {
  .ext-fab.is-busy,
  .ext-fab.is-busy::after,
  .ext-fab.is-busy .ext-fab-icon { animation: none; }
  .ext-fab.is-busy::after { opacity: 0.6; }
  .ext-fab-badge { animation: none; }
}
.ext-fab-label {
  position: absolute;
  right: 56px;
  top: 50%;
  transform: translateY(-50%);
  background: rgba(0, 0, 0, 0.72);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 5px 10px;
  border-radius: 6px;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}
.ext-fab:hover .ext-fab-label {
  opacity: 1;
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

<!-- 全局（非 scoped）：悬浮面板呼出时锁定背景滚动，需作用在 body 上 -->
<style>
body.ext-no-scroll {
  overflow: hidden;
}
</style>
