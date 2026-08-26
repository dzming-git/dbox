<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { scriptApi } from '../api/script'
import { useUserStore } from '../stores/userStore'
import { withExtRuntime } from '../utils/extRuntime'

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
// 统一 apps 启动器入口：以「应用」按钮的形式注入全局导航栏（见 App.vue 的 #ext-launcher-slot），
// 点击在导航栏下方展开 apps 列表。刻意不用右下角常驻悬浮球——浮层无论怎么调位置都会遮挡
// 页面内容或扩展自身的操作区（曾靠「全屏时隐藏」规避），放进导航栏后从结构上不存在遮挡。
const launcherOpen = ref(false)
// 导航栏挂载点是否已存在（登录页无导航栏，此时不渲染入口，避免 Teleport 找不到目标）
const navSlotReady = ref(false)
function checkNavSlot() {
  navSlotReady.value = !!document.getElementById('ext-launcher-slot')
}
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
  // 优先用 Pinia userStore 里的 token（与 media.ts / axios 拦截器同源），
  // 兜底读 localStorage，确保传给 iframe 的一定是当前登录用户的 token。
  const store = useUserStore()
  const raw = store.token || localStorage.getItem('token') || localStorage.getItem('access_token') || sessionStorage.getItem('token')
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
  // 每次打开都刷新 token（用户可能刚登录/刷新过 token），确保推给 iframe 的是最新值
  await loadToken()
  // 每次打开都重新拉取最新 panel.html：后端已设 no-store，但 Vue 变量缓存会让旧版本
  // 残留（导致新功能不生效）。重新获取成本极低，优先保证 UI 最新。
  try {
    const res: any = await scriptApi.getPanel(id)
    // 前置共享运行时：与全屏页共用同一份数据缓存，形态切换不再重复加载
    panelHtml.value[id] = withExtRuntime(res, id)
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

// apps 启动器点击：切换抽屉。若已打开某 app 面板，则先收起该面板，再展开 app 列表
function toggleLauncher() {
  launcherOpen.value = !launcherOpen.value
  if (launcherOpen.value) openId.value = null
}

function pushToken(id: string) {
  const iframe = document.getElementById(`ext-frame-${id}`) as HTMLIFrameElement | null
  if (iframe?.contentWindow) {
    // 推送前实时读取最新 token：主站 axios 会在 401 时静默刷新并写回 localStorage，
    // 若仍用组件挂载时缓存的 token.value 会给 iframe 过期 token，导致插件接口 401。
    const fresh = localStorage.getItem('token')
      || localStorage.getItem('access_token')
      || sessionStorage.getItem('token')
      || token.value
    iframe.contentWindow.postMessage({ type: 'DBOX_TOKEN', token: fresh }, '*')
    iframe.contentWindow.postMessage({ type: 'DBOX_DRAFT', text: drafts.value[id] || '' }, '*')
    const ext = extensions.value.find((e) => e.id === id)
    if (ext?.ui?.standalone_route) {
      iframe.contentWindow.postMessage(
        { type: 'DBOX_EXT_INFO', standalone_route: ext.ui.standalone_route }, '*')
    }
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

// 点击面板以外（遮罩层）时自动收起：同时关闭已打开的 app 面板与 app 列表抽屉
function closePanel() {
  openId.value = null
  launcherOpen.value = false
}

// 框架层统一提供的「全屏」入口：任何声明了 standalone_route 的扩展自动获得。
// 直接路由跳转并收起浮层面板；预览上下文由各扩展在自己的 panel.html 中经
// localStorage 持久化，全屏页（ExtensionStandalone）加载后自动恢复。
function openStandalone(ext: Extension) {
  if (!ext.ui.standalone_route) return
  openId.value = null
  router.push(ext.ui.standalone_route)
}

// 列表是导航栏下拉菜单，用「点击外部收起」而非全屏遮罩，避免遮罩压住导航栏入口本身
function onDocClick(e: MouseEvent) {
  if (!launcherOpen.value) return
  const t = e.target as HTMLElement | null
  if (t?.closest('.ext-launcher') || t?.closest('.ext-nav-trigger')) return
  launcherOpen.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (launcherOpen.value) launcherOpen.value = false
  else if (openId.value) openId.value = null
}

onMounted(async () => {
  await loadToken()
  await loadExtensions()
  window.addEventListener('message', onMessage)
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
  await nextTick()
  checkNavSlot()
  syncOverlayFlags()
  pollBusy()
  busyTimer = setInterval(pollBusy, 2000)
})

onUnmounted(() => {
  window.removeEventListener('message', onMessage)
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
  if (busyTimer) clearInterval(busyTimer)
  document.body.classList.remove('ext-no-scroll')
  document.body.classList.remove('ext-panel-open')
})

// 呼出悬浮面板（带遮罩）时：锁定背景滚动，并把导航栏抬到遮罩之上，
// 保证「应用」入口在面板打开时依然可点（可一次点击就切回应用列表）。
function syncOverlayFlags() {
  const ext = openId.value ? extensions.value.find((e) => e.id === openId.value) : null
  const floating = !!(openId.value && ext?.ui?.mount === 'floating')
  document.body.classList.toggle('ext-no-scroll', floating)
  document.body.classList.toggle('ext-panel-open', floating)
}

watch(openId, (id) => {
  if (id) {
    pushToken(id)
    if (unreadMap.value[id]) unreadMap.value = { ...unreadMap.value, [id]: 0 }
  }
  syncOverlayFlags()
})

// 路由变化时：收起应用列表（导航栏菜单跳转后应关闭）；若进入某扩展独立全屏页，
// 视为已查看，清空未读角标。面板本身不强制收起，保留 DBOX_NAVIGATE 的 keepPanel 语义。
watch(() => route.path, async (p) => {
  launcherOpen.value = false
  for (const ext of extensions.value) {
    const rp = ext.ui?.standalone_route
    if (rp && p === rp && unreadMap.value[ext.id]) {
      unreadMap.value = { ...unreadMap.value, [ext.id]: 0 }
    }
  }
  // 登录页无导航栏，进出登录页时重新确认挂载点是否存在
  await nextTick()
  checkNavSlot()
})
</script>

<template>
  <div class="ext-host">
    <!-- 展开面板时的遮罩：拦截页面点击，点击遮罩收起。
         应用列表是导航栏下拉菜单，不再使用遮罩（改为点击外部收起），避免压住导航栏入口。 -->
    <div v-if="openId" class="ext-mask" @click="closePanel"></div>

    <!-- 统一的 apps 启动器入口：注入全局导航栏（与「任务」「稍后再看」等图标同排） -->
    <Teleport v-if="navSlotReady && extensions.length" to="#ext-launcher-slot">
      <button
        type="button"
        class="nav-link nav-icon-link ext-nav-trigger"
        :class="{ 'is-open': launcherOpen, 'is-busy': anyBusy }"
        title="应用"
        @click="toggleLauncher"
      >
        <span class="ext-nav-ico-wrap">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1.5"/>
            <rect x="14" y="3" width="7" height="7" rx="1.5"/>
            <rect x="3" y="14" width="7" height="7" rx="1.5"/>
            <rect x="14" y="14" width="7" height="7" rx="1.5"/>
          </svg>
          <span v-if="totalUnread" class="ext-nav-badge">{{ totalUnread > 99 ? '99+' : totalUnread }}</span>
          <span v-else-if="anyBusy" class="ext-nav-dot"></span>
        </span>
        <span>应用</span>
      </button>
    </Teleport>

    <!-- apps 列表（导航栏下方的下拉面板） -->
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

    <!-- 各扩展的面板（用 v-show 而非 v-if，切换 app 时保留 iframe 状态避免中断） -->
    <template v-for="ext in extensions" :key="ext.id">
      <!-- 浮动面板 -->
      <div
        v-show="ext.ui.mount === 'floating' && openId === ext.id"
        class="ext-panel"
      >
        <div class="ext-panel-header">
          <span>{{ ext.ui.title }}</span>
          <div class="ext-panel-actions">
            <button
              v-if="ext.ui.standalone_route"
              class="ext-fs"
              title="在独立页面全屏打开"
              @click="openStandalone(ext)"
            >⛶ 全屏</button>
            <button class="ext-close" @click="openId = null">×</button>
          </div>
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
        v-show="ext.ui.mount === 'panel' && openId === ext.id"
        class="ext-side-panel"
      >
        <div class="ext-side-header">
          <span>{{ ext.ui.title }}</span>
          <div class="ext-panel-actions">
            <button
              v-if="ext.ui.standalone_route"
              class="ext-fs"
              title="在独立页面全屏打开"
              @click="openStandalone(ext)"
            >⛶ 全屏</button>
            <button class="ext-close" @click="openId = null">×</button>
          </div>
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

/* ---- apps 启动器入口（导航栏图标按钮，样式继承 App.vue 的 .nav-icon-link） ---- */
.ext-nav-trigger {
  background: transparent;
  border: none;
  font: inherit;
  cursor: pointer;
  color: var(--text-secondary, #bbb);
}
.ext-nav-trigger:hover {
  color: var(--text-primary, #eee);
  background: var(--bg-surface-hover, rgba(255, 255, 255, 0.06));
}
.ext-nav-trigger.is-open {
  color: var(--text-primary, #eee);
  background: var(--accent-soft, rgba(79, 140, 255, 0.16));
}
.ext-nav-trigger.is-busy {
  color: var(--accent, #4f8cff);
}
.ext-nav-ico-wrap {
  position: relative;
  display: inline-flex;
}
.ext-nav-badge {
  position: absolute;
  top: -6px;
  right: -10px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--danger, #f5455c);
  color: var(--text-on-accent, #fff);
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  font-weight: 600;
  pointer-events: none;
}
/* 后台有任务在跑时的轻量提示（不抢眼、不遮挡，取代原悬浮球的呼吸/转圈动画） */
.ext-nav-dot {
  position: absolute;
  top: -2px;
  right: -4px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent, #4f8cff);
  animation: ext-dot-pulse 1.4s ease-in-out infinite;
  pointer-events: none;
}
@keyframes ext-dot-pulse {
  0%, 100% { opacity: 0.35; transform: scale(0.85); }
  50% { opacity: 1; transform: scale(1.15); }
}
@media (prefers-reduced-motion: reduce) {
  .ext-nav-dot { animation: none; opacity: 0.8; }
}

/* ---- apps 列表（挂在导航栏下方的下拉面板） ---- */
.ext-launcher {
  position: fixed;
  top: calc(var(--nav-height, 60px) + 6px);
  right: 12px;
  width: 320px;
  max-width: calc(100vw - 24px);
  max-height: calc(100vh - var(--nav-height, 60px) - 24px);
  max-height: calc(100dvh - var(--nav-height, 60px) - 24px);
  background: var(--bg-elevated, #1e1e22);
  border: 1px solid var(--border-default, #333);
  border-radius: 14px;
  z-index: 9004;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
@media (max-width: 600px) {
  .ext-launcher {
    left: 8px;
    right: 8px;
    width: auto;
  }
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
  transform: translateY(-8px);
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
.ext-panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ext-fs {
  background: var(--accent, #4f8cff);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  padding: 4px 10px;
  cursor: pointer;
  line-height: 1.4;
}
.ext-fs:hover {
  filter: brightness(1.08);
}
/* 浮动面板同样从导航栏入口下方展开（与入口位置呼应），不再占用右下角，
   避免压住页面底部内容与扩展面板自身的底部操作区（如输入框「发送」按钮）。 */
.ext-panel {
  position: fixed;
  top: calc(var(--nav-height, 60px) + 6px);
  right: 12px;
  width: 380px;
  max-width: calc(100vw - 24px);
  height: 520px;
  max-height: calc(100vh - var(--nav-height, 60px) - 24px);
  max-height: calc(100dvh - var(--nav-height, 60px) - 24px);
  background: var(--bg-elevated, #1e1e22);
  border: 1px solid var(--border-default, #333);
  border-radius: 12px;
  z-index: 9001;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}
/* 手机端：铺满导航栏以下的可视区域，输入区不再被任何浮层压住 */
@media (max-width: 600px) {
  .ext-panel {
    left: 8px;
    right: 8px;
    width: auto;
    height: calc(100vh - var(--nav-height, 60px) - 16px);
    height: calc(100dvh - var(--nav-height, 60px) - 16px);
  }
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
/* 浮动面板呼出时把导航栏抬到遮罩（z-index 8999）之上：
   保证导航栏里的「应用」入口在面板打开时仍可点击，一次点击即可切回应用列表。
   竖屏沉浸播放器是 z-index 2000 的全屏浮层，此时不抬高，避免导航栏钻到视频上方。 */
body.ext-panel-open:not(.portrait-mode-active) .nav {
  z-index: 9003;
}
/* 说明：入口已内嵌到全局导航栏，凡是隐藏导航栏的场景（扩展独立全屏页 ext-standalone、
   图集阅读器 reader-active、竖屏沉浸播放器全屏覆盖）入口都会随之消失，
   无需再为「浮球遮挡内容」单独写隐藏规则。 */
</style>
