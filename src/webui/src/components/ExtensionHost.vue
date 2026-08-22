<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { scriptApi } from '../api/script'

const router = useRouter()
const route = useRoute()

interface ExtensionUI {
  mount: string
  title: string
  icon: string
  entry?: string
  needs_credential: boolean
  sandbox: string
  standalone_route?: string
  busy_poll?: string
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
// 忙碌态：由宿主侧轻量轮询后端任务接口得到「是否有正在处理/排队的任务」，
// 与面板 iframe 生命周期解耦——即使面板收起（iframe 被卸载），
// 入口也能在后台工作时持续显示忙碌动画。
const busyMap = ref<Record<string, boolean>>({})
function fabBusy(id: string) { return !!busyMap.value[id] }
// 未读提醒：面板收起期间若有任务产出结果（history 顶部变化），累计未读数，
// 入口显示角标，避免用户忘记曾布置过任务。打开面板即清空未读。
const unreadMap = ref<Record<string, number>>({})
function fabUnread(id: string) { return unreadMap.value[id] || 0 }
// 用户「正在查看某扩展」的两种情形：面板展开 / 处于该扩展的独立全屏路由。
function isViewing(id: string): boolean {
  if (openId.value === id) return true
  const ext = extensions.value.find((e) => e.id === id)
  const routePath = ext?.ui?.standalone_route
  return !!(routePath && route.path === routePath)
}

// ---- apps 启动器状态 ----
// 右下角统一 apps 启动器：点击弹出 apps 列表（所有扩展的图标入口）。
const launcherOpen = ref(false)
// 聚合所有扩展的未读总数（app 启动器右上角角标）
const totalUnread = computed(() =>
  Object.values(unreadMap.value).reduce((a, b) => a + b, 0),
)
// 聚合忙碌态：任一扩展在处理中即视为忙碌
const anyBusy = computed(() => extensions.value.some((e) => fabBusy(e.id)))

// 每个扩展独立维护轮询基线（最近一条已完成任务 id），避免相互干扰。
const lastTopById = ref<Record<string, string | null>>({})
const seededById = ref<Record<string, boolean>>({})
let busyTimer: any = null
async function pollBusy() {
  // 仅轮询声明了 ui.busy_poll 的扩展（如 AI 助手）。
  const targets = extensions.value.filter((e) => e.ui?.busy_poll)
  if (!targets.length) { busyMap.value = {}; unreadMap.value = {}; return }
  const headers: Record<string, string> = {}
  if (token.value) headers['Authorization'] = 'Bearer ' + token.value
  for (const ext of targets) {
    const id = ext.id
    try {
      const resp = await fetch(ext.ui!.busy_poll as string, { headers })
      if (!resp.ok) continue
      const d: any = await resp.json()
      busyMap.value = { ...busyMap.value, [id]: !!(d.active) || (d.pending && d.pending.length > 0) }
      const topId = d.history && d.history.length ? d.history[0].id : null
      const lastTop = lastTopById.value[id] ?? null
      if (topId && topId !== lastTop) {
        // 面板未展开「且」未处于全屏页时，才累计未读；正在看则不算未读
        if ((seededById.value[id]) && !isViewing(id)) {
          unreadMap.value = { ...unreadMap.value, [id]: (unreadMap.value[id] || 0) + 1 }
        }
        lastTopById.value = { ...lastTopById.value, [id]: topId }
      }
      seededById.value = { ...seededById.value, [id]: true }
    } catch (e) { /* 单个扩展网络抖动忽略，下个周期重试 */ }
  }
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

// 打开某扩展的面板（浮动/侧边面板），并加载其 panel.html
async function openPanel(id: string) {
  openId.value = id
  const ext = extensions.value.find((e) => e.id === id)
  if (!ext?.ui.entry) return
  // 每次打开都重新拉取最新 panel.html：后端已设 no-store，但 Vue 变量缓存会让旧版本
  // 残留（导致新功能不生效）。重新获取成本极低，优先保证 UI 最新。
  try {
    const res: any = await scriptApi.getPanel(id)
    panelHtml.value[id] = res
  } catch (e) {
    panelHtml.value[id] = '<p style="color:#f66;padding:12px">面板加载失败</p>'
  }
  await nextTick()
  pushToken(id)
}

// apps 列表点击某 app：打开对应面板（floating → 浮动面板；panel → 侧边面板）。
// 独立全屏路由 standalone_route 保留给面板内「全屏」入口或导航，不在此自动跳转，
// 以维持右下角浮层内的即时操作体验。
async function openApp(id: string) {
  launcherOpen.value = false
  await openPanel(id)
}

// apps 启动器点击：切换抽屉
function toggleLauncher() {
  launcherOpen.value = !launcherOpen.value
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
  // iframe 请求父页面跳转（如面板中点击反馈单引用，跳转到反馈中心详情）。
  if (e.data?.type === 'DBOX_NAVIGATE' && e.data.path) {
    if (e.data.path === '__back__') router.back()
    else router.push(e.data.path)
    // 除非显式声明 keepPanel，否则跳转后收起面板
    if (e.data.keepPanel !== true) {
      openId.value = null
    }
  }
}

// 点击面板以外（遮罩层）时自动收起
function closePanel() {
  openId.value = null
}

onMounted(async () => {
  await loadToken()
  await loadExtensions()
  window.addEventListener('message', onMessage)
  syncScrollLock()
  pollBusy()
  busyTimer = setInterval(pollBusy, 2000)
})

onUnmounted(() => {
  window.removeEventListener('message', onMessage)
  if (busyTimer) clearInterval(busyTimer)
  document.body.classList.remove('ext-no-scroll')
})

// 呼出悬浮面板（带遮罩）时锁定背景滚动
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
    if (unreadMap.value[id]) unreadMap.value = { ...unreadMap.value, [id]: 0 }
  }
  syncScrollLock()
})

// 路由变化时：若进入某扩展独立全屏页，视为已查看，清空未读角标
watch(() => route.path, (p) => {
  for (const ext of extensions.value) {
    const rp = ext.ui?.standalone_route
    if (rp && p === rp && unreadMap.value[ext.id]) {
      unreadMap.value = { ...unreadMap.value, [ext.id]: 0 }
    }
  }
})
</script>

<template>
  <div class="ext-host">
    <!-- 展开面板时的遮罩：拦截页面点击，点击遮罩收起 -->
    <div v-if="openId || launcherOpen" class="ext-mask" @click="closePanel"></div>

    <!-- 统一的 apps 启动器（右下角单个悬浮球） -->
    <div
      class="ext-launcher-fab"
      :class="{ 'is-open': launcherOpen, 'is-busy': anyBusy }"
      title="应用"
      @click.stop="toggleLauncher"
    >
      <svg class="launcher-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <rect x="3" y="3" width="7" height="7" rx="1.5"/>
        <rect x="14" y="3" width="7" height="7" rx="1.5"/>
        <rect x="3" y="14" width="7" height="7" rx="1.5"/>
        <rect x="14" y="14" width="7" height="7" rx="1.5"/>
      </svg>
      <span v-if="totalUnread" class="ext-fab-badge">{{ totalUnread > 99 ? '99+' : totalUnread }}</span>
    </div>

    <!-- apps 列表抽屉 -->
    <transition name="launcher">
      <div v-if="launcherOpen" class="ext-launcher" @click.stop>
        <div class="ext-launcher-header">
          <span>应用</span>
          <button class="ext-close" @click="launcherOpen = false">×</button>
        </div>
        <div class="ext-launcher-grid">
          <button
            v-for="ext in extensions"
            :key="ext.id"
            class="ext-app"
            @click="openApp(ext.id)"
          >
            <span class="ext-app-icon">{{ ext.ui.icon || '🔧' }}</span>
            <span class="ext-app-name">{{ ext.ui.title || ext.name }}</span>
            <span v-if="fabUnread(ext.id)" class="ext-app-badge">{{ fabUnread(ext.id) > 99 ? '99+' : fabUnread(ext.id) }}</span>
          </button>
          <div v-if="!extensions.length" class="ext-launcher-empty">
            暂无可用应用
          </div>
        </div>
      </div>
    </transition>

    <!-- 各扩展的面板（展开时渲染） -->
    <template v-for="ext in extensions" :key="ext.id">
      <!-- 浮动面板 -->
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
        <div class="ext-side-header">
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

/* ---- apps 启动器球 ---- */
.ext-launcher-fab {
  position: fixed;
  right: 16px;
  bottom: 18px;
  height: 48px;
  width: 48px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: var(--accent, #4f8cff);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18);
  z-index: 9000;
  opacity: 0.9;
  overflow: visible;
  transition: opacity 0.15s, transform 0.15s, box-shadow 0.15s;
}
.ext-launcher-fab:hover,
.ext-launcher-fab.is-open {
  opacity: 1;
  transform: scale(1.08);
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.25);
}
.launcher-icon {
  display: block;
}
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
}
.ext-launcher-fab.is-busy {
  animation: fab-breathe 1.8s ease-in-out infinite;
}
.ext-launcher-fab.is-busy::after {
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
@keyframes fab-spin { to { transform: rotate(360deg); } }
@keyframes fab-breathe {
  0%, 100% { box-shadow: 0 2px 10px rgba(0, 0, 0, 0.18); }
  50% { box-shadow: 0 0 0 6px rgba(79, 140, 255, 0.16), 0 6px 18px rgba(79, 140, 255, 0.5); }
}
@media (prefers-reduced-motion: reduce) {
  .ext-launcher-fab.is-busy,
  .ext-launcher-fab.is-busy::after { animation: none; }
  .ext-launcher-fab.is-busy::after { opacity: 0.6; }
}

/* ---- apps 列表抽屉 ---- */
.ext-launcher {
  position: fixed;
  right: 20px;
  bottom: 84px;
  width: 320px;
  max-width: 92vw;
  max-height: 70vh;
  background: var(--bg-elevated, #1e1e22);
  border: 1px solid var(--border-default, #333);
  border-radius: 14px;
  z-index: 9001;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
.ext-launcher-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--bg-surface-2, #2a2a30);
  color: var(--text-primary, #eee);
  font-size: 14px;
  font-weight: 600;
}
.ext-launcher-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(76px, 1fr));
  gap: 12px;
  padding: 16px;
  overflow-y: auto;
}
.ext-launcher-empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 32px 0;
  color: var(--text-tertiary, #888);
  font-size: 13px;
}
.ext-app {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 14px 6px;
  background: var(--bg-surface, #232329);
  border: 1px solid var(--border-subtle, #2e2e34);
  border-radius: 12px;
  cursor: pointer;
  transition: transform 0.12s, border-color 0.12s, background 0.12s;
}
.ext-app:hover {
  transform: translateY(-2px);
  border-color: var(--accent, #4f8cff);
  background: var(--bg-surface-2, #2a2a30);
}
.ext-app-icon {
  font-size: 28px;
  line-height: 1;
}
.ext-app-name {
  font-size: 12px;
  color: var(--text-secondary, #bbb);
  text-align: center;
  line-height: 1.3;
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.ext-app-badge {
  position: absolute;
  top: 6px;
  right: 6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: #f5455c;
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  line-height: 16px;
  text-align: center;
}
.launcher-enter-active,
.launcher-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}
.launcher-enter-from,
.launcher-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

/* ---- 面板 ---- */
.ext-close {
  background: none;
  border: none;
  color: var(--text-secondary, #aaa);
  font-size: 20px;
  cursor: pointer;
  line-height: 1;
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
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.4);
}
.ext-side-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  background: var(--bg-surface-2, #2a2a30);
  color: var(--text-primary, #eee);
  font-size: 14px;
  font-weight: 600;
  flex-shrink: 0;
}
</style>

<!-- 全局（非 scoped）：悬浮面板呼出时锁定背景滚动，需作用在 body 上 -->
<style>
body.ext-no-scroll {
  overflow: hidden;
}
/* 竖屏沉浸模式下隐藏 apps 启动器，避免遮挡视频内容 */
body.portrait-mode-active .ext-launcher-fab {
  display: none !important;
}
</style>
