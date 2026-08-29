<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { scriptApi } from '../api/script'
import { useUserStore } from '../stores/userStore'
import { withExtRuntime } from '../utils/extRuntime'
import {
  ensurePanel, setPanelMode, postToPanel, getPanelIframe,
  onPanelMessage, isPanelVisible,
} from '../utils/extPanelHost'

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

// 扩展图标：内联 SVG（<svg...）用 v-html 渲染以继承 currentColor 自适应明暗主题；
// http(s) 图片地址或 data: URI 用 <img> 渲染；其余当文本（emoji）显示。
function isSvgIcon(s: unknown): boolean {
  return typeof s === 'string' && /^\s*<svg[\s>]/i.test(s)
}
function isImageIcon(s: unknown): boolean {
  return typeof s === 'string' && /^(https?:\/\/|data:image\/)/i.test(s)
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
  // 全屏页由 extPanelHost 把形态切成 fullscreen，据此判断「正在查看」，
  // 与路由解耦（面板实例是常驻的，路由只是触发形态切换）。
  if (isPanelVisible(id)) return true
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
  // 仅轮询声明了 ui.busy_poll 的扩展（如 CodeBuddy）。
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
  // 取最新 panel.html（后端 no-store）：仅在该扩展**首次**打开时写入 iframe srcdoc。
  // 之后再打开只切换形态（纯 CSS），绝不重建文档——否则滚动位置/输入内容/播放进度会丢。
  try {
    const res: any = await scriptApi.getPanel(id)
    // 前置共享运行时：与全屏页共用同一份数据缓存，形态切换不再重复加载
    panelHtml.value[id] = withExtRuntime(res, id)
  } catch (e) {
    panelHtml.value[id] = '<p style="color:#f66;padding:12px">面板加载失败</p>'
  }
  const already = !!getPanelIframe(id)
  ensurePanel(id, {
    html: panelHtml.value[id] || '',
    sandbox: ext?.ui?.sandbox,
    title: ext?.ui?.title || id,
    standaloneRoute: ext?.ui?.standalone_route,
  })
  if (!already) {
    await nextTick()
  }
  // 切到小窗形态：DOM 与 iframe 文档不动，面板内现场原样保留
  setPanelMode(id, 'floating')
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
  if (!getPanelIframe(id)) return
  // 推送前实时读取最新 token：主站 axios 会在 401 时静默刷新并写回 localStorage，
  // 若仍用组件挂载时缓存的 token.value 会给 iframe 过期 token，导致插件接口 401。
  const fresh = localStorage.getItem('token')
    || localStorage.getItem('access_token')
    || sessionStorage.getItem('token')
    || token.value
  postToPanel(id, { type: 'DBOX_TOKEN', token: fresh })
  postToPanel(id, { type: 'DBOX_DRAFT', text: drafts.value[id] || '' })
  const ext = extensions.value.find((e) => e.id === id)
  if (ext?.ui?.standalone_route) {
    postToPanel(id, { type: 'DBOX_EXT_INFO', standalone_route: ext.ui.standalone_route })
  }
}

// 处理面板（iframe）发来的消息。由 extPanelHost 统一接收并带 extId 分发。
function handlePanelMessage(data: any, id: string) {
  if (!data || !id) return
  // 面板反向请求 token（例如刚挂载时）
  if (data.type === 'DBOX_REQUEST_TOKEN') pushToken(id)
  // 面板同步未发送的输入内容，供收起后再展开时恢复
  if (data.type === 'DBOX_DRAFT_SAVE') {
    drafts.value[id] = typeof data.text === 'string' ? data.text : ''
  }
  // 面板请求父页面跳转（如面板中点击资源引用，跳转到对应详情页）。
  if (data.type === 'DBOX_NAVIGATE' && data.path) {
    if (data.path === '__back__') router.back()
    else router.push(data.path)
    // 除非显式声明 keepPanel，否则跳转后收起面板
    if (data.keepPanel !== true) openId.value = null
  }
}

// 点击面板以外（遮罩层）时自动收起：同时关闭已打开的 app 面板与 app 列表抽屉
function closePanel() {
  openId.value = null
  launcherOpen.value = false
}

// 面板自身「收起」按钮或窗外遮罩点击触发（由框架层 extPanelHost 派发）。
// 必须清掉 openId：否则 body 的 ext-no-scroll（overflow:hidden）残留，
// 导致小窗收起后首页无法上下滑动（仅下拉刷新因监听自身 touch 而仍可用）。
function onCollapse(_e: Event) {
  openId.value = null
}

// 注：「全屏」入口已由框架层 extPanelHost 内建在面板标题栏上（任何声明了
// standalone_route 的扩展自动获得）。点击后派发 dbox-ext-request-fullscreen，
// 由上面的 onRequestFullscreen 只做路由跳转，不重建 iframe。

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

// 面板标题栏「全屏」按钮（由 extPanelHost 内建）触发：只切路由，不动 iframe
function onRequestFullscreen(e: Event) {
  const d = (e as CustomEvent).detail || {}
  if (d.route) {
    openId.value = null
    router.push(d.route)
  }
}

let offPanelMsg: (() => void) | null = null

onMounted(async () => {
  await loadToken()
  await loadExtensions()
  // 统一走 extPanelHost 的消息通道（面板实例常驻，不再各自监听 window）
  offPanelMsg = onPanelMessage((msg, extId) => handlePanelMessage(msg, extId))
  window.addEventListener('dbox-ext-request-fullscreen', onRequestFullscreen as EventListener)
  window.addEventListener('dbox-ext-collapse', onCollapse as EventListener)
  document.addEventListener('click', onDocClick)
  document.addEventListener('keydown', onKeydown)
  await nextTick()
  checkNavSlot()
  syncOverlayFlags()
  pollBusy()
  busyTimer = setInterval(pollBusy, 2000)
})

onUnmounted(() => {
  if (offPanelMsg) { offPanelMsg(); offPanelMsg = null }
  window.removeEventListener('dbox-ext-request-fullscreen', onRequestFullscreen as EventListener)
  window.removeEventListener('dbox-ext-collapse', onCollapse as EventListener)
  document.removeEventListener('click', onDocClick)
  document.removeEventListener('keydown', onKeydown)
  if (busyTimer) clearInterval(busyTimer)
  document.body.classList.remove('ext-no-scroll')
  document.body.classList.remove('ext-panel-open')
})

// 呼出悬浮面板（带遮罩）时：锁定背景滚动，并把导航栏抬到遮罩之上，
// 保证「应用」入口在面板打开时依然可点（可一次点击就切回应用列表）。
function syncOverlayFlags() {
  const floating = !!openId.value
  document.body.classList.toggle('ext-no-scroll', floating)
  document.body.classList.toggle('ext-panel-open', floating)
}

watch(openId, (id, prev) => {
  if (id) {
    pushToken(id)
    if (unreadMap.value[id]) unreadMap.value = { ...unreadMap.value, [id]: 0 }
  }
  // 收起（openId 置空）时把上一个面板切到 hidden：仅隐藏，iframe 文档保留，
  // 下次打开仍是收起前的现场（滚动位置、输入内容、播放进度都在）。
  if (!id && prev && getPanelIframe(prev)) {
    setPanelMode(prev, 'hidden')
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
            <span v-if="isSvgIcon(ext.ui.icon)" class="ext-app-icon" v-html="ext.ui.icon"></span>
            <img v-else-if="isImageIcon(ext.ui.icon)" class="ext-app-icon-img" :src="ext.ui.icon" alt="" />
            <span v-else class="ext-app-icon">{{ ext.ui.icon || '🔧' }}</span>
            <span class="ext-app-name">{{ ext.ui.title || ext.name }}</span>
            <span v-if="fabUnread(ext.id)" class="ext-app-badge">{{ fabUnread(ext.id) > 99 ? '99+' : fabUnread(ext.id) }}</span>
          </button>
          <div v-if="!extensions.length" class="ext-launcher-empty">
            暂无可用应用
          </div>
        </div>
      </div>
    </transition>

    <!--
      各扩展的面板 iframe 已由框架层 extPanelHost 统一管理：
      常驻在 body 下的单一容器里，形态（小窗/全屏/收起）只切 CSS，
      DOM 与 iframe 文档从不移动或重建，因此面板内的滚动位置、输入内容、
      播放进度在切换形态与收起后重新打开时都原样保留。
      这里不再渲染 iframe，仅保留遮罩层（点击遮罩收起面板）。
    -->
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
.ext-app-icon-img {
  width: 28px;
  height: 28px;
  object-fit: contain;
  border-radius: 6px;
}
/* 内联 SVG 图标：约束尺寸并继承文字色（fill=currentColor 时自适应明暗主题） */
.ext-app-icon svg {
  width: 28px;
  height: 28px;
  display: block;
  fill: currentColor;
  color: inherit;
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
/* 注：面板容器（小窗/全屏/收起）与 iframe 的样式已统一由框架层 extPanelHost
   内联提供，本组件不再持有 .ext-panel / .ext-side-panel / .ext-frame 等样式——
   面板实例是常驻在 body 下的单一节点，形态只由 extPanelHost 的 CSS 表达。 */
.ext-panel-actions {
  display: flex;
  align-items: center;
  gap: 8px;
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
