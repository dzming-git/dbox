<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'

interface PlayItem {
  src: string
  poster?: string
  title?: string
  // 竖屏互动状态（由调用方传入当前视频的点赞/收藏/屏蔽状态与计数）
  hash?: string
  like_count?: number
  favorite_count?: number
  is_liked?: boolean
  is_favorited?: boolean
  is_disliked?: boolean
}

const props = withDefaults(
  defineProps<{
    playlist: PlayItem[] // 视频列表（按播放顺序）；单视频时长度为 1
    initialIndex?: number
    autoplay?: boolean
    enablePortrait?: boolean // 是否启用组件内竖屏模式；false 时隐藏竖屏入口且竖屏按钮无效
    // 是否展示竖屏互动功能（双击点赞/收藏/不喜欢/更多菜单）；false 时竖屏仅播放+上下滑
    portraitInteractions?: boolean
    // 竖屏上滑到列表末尾时回调，用于加载下一个（无限流）；返回项则追加到 playlist
    loadMore?: (item: PlayItem) => Promise<PlayItem | null | undefined> | PlayItem | null | undefined
  }>(),
  { initialIndex: 0, autoplay: false, enablePortrait: true, portraitInteractions: true }
)

const emit = defineEmits<{
  (e: 'update:index', index: number): void
  (e: 'ended', index: number): void
  (e: 'play', currentTime: number): void
  (e: 'pause', currentTime: number): void
  (e: 'timeupdate', currentTime: number): void
  (e: 'seeked', currentTime: number): void
  // 竖屏互动动作（由调用方实现具体业务）
  (e: 'like', item: PlayItem): void
  (e: 'favorite', item: PlayItem): void
  (e: 'dislike', item: PlayItem): void
  (e: 'open-detail', item: PlayItem): void
  (e: 'toggle-landscape', item: PlayItem): void
}>()

// ===== 模式 =====
type Mode = 'normal' | 'portrait'
const mode = ref<Mode>('normal')
const curIndex = ref(Math.max(0, Math.min(props.initialIndex, props.playlist.length - 1)))

// ===== 主播放器（正常模式） =====
const player = ref<HTMLVideoElement | null>(null)
const isPlaying = ref(false)
const isBuffering = ref(false)
const netSpeed = ref(0) // KB/s
const currentTime = ref(0)
const duration = ref(0)
const showControls = ref(true)
let controlsTimer: number | null = null
let speedTimer: number | null = null
let speedBytesStart = 0
let speedTimeStart = 0

const currentItem = computed(() => props.playlist[curIndex.value] || props.playlist[0])

function togglePlay() {
  const p = player.value
  if (!p) return
  if (p.paused) p.play().catch(() => {})
  else p.pause()
}

function onLoadedMetadata() {
  if (player.value) duration.value = player.value.duration || 0
}
function onTimeUpdate() {
  if (player.value) currentTime.value = player.value.currentTime
  emit('timeupdate', currentTime.value)
}
function onPlay() {
  isPlaying.value = true
  showControlsTemporarily()
  emit('play', currentTime.value)
}
function onPause() {
  isPlaying.value = false
  isBuffering.value = false
  showControls.value = true
  netSpeed.value = 0
  stopSpeedMonitor()
  if (controlsTimer) window.clearTimeout(controlsTimer)
  emit('pause', currentTime.value)
}
function onWaiting() {
  isBuffering.value = true
  showControls.value = true
  if (controlsTimer) window.clearTimeout(controlsTimer)
  startSpeedMonitor()
}
function onPlaying() {
  isBuffering.value = false
  startSpeedMonitor()
}
function onSeeked() {
  emit('seeked', currentTime.value)
}
function onEnded() {
  isBuffering.value = false
  netSpeed.value = 0
  stopSpeedMonitor()
  emit('ended', curIndex.value)
}

// 供父组件（如 Video.vue 竖屏槽位、业务代码）调用 / 访问
function seekTo(t: number) {
  if (player.value) player.value.currentTime = t
}
function play() { player.value?.play().catch(() => {}) }
function pause() { player.value?.pause() }
function setMuted(v: boolean) { if (player.value) player.value.muted = v }
defineExpose({
  play,
  pause,
  seekTo,
  setMuted,
  enterPortraitMode,
  exitPortraitMode,
  get el() { return player.value },
  get currentTime() { return currentTime.value },
  get duration() { return duration.value },
})

// 控制栏自动隐藏
function showControlsTemporarily() {
  showControls.value = true
  if (controlsTimer) window.clearTimeout(controlsTimer)
  controlsTimer = window.setTimeout(() => {
    if (isPlaying.value && !isBuffering.value) showControls.value = false
  }, 3000)
}

// 网速监测
function startSpeedMonitor() {
  if (speedTimer) window.clearInterval(speedTimer)
  const v = player.value
  if (!v || !v.buffered.length) return
  speedBytesStart = v.buffered.end(v.buffered.length - 1) * (v.videoWidth * v.videoHeight * 0.08)
  speedTimeStart = performance.now()
  speedTimer = window.setInterval(() => {
    const el = player.value
    if (!el || !el.buffered.length) return
    const end = el.buffered.end(el.buffered.length - 1)
    const bytes = end * (el.videoWidth * el.videoHeight * 0.08)
    const dt = (performance.now() - speedTimeStart) / 1000
    if (dt > 0) {
      const kbps = (bytes - speedBytesStart) / 1024 / dt
      netSpeed.value = kbps > 0 ? kbps : 0
    }
    speedBytesStart = bytes
    speedTimeStart = performance.now()
  }, 1000)
}
function stopSpeedMonitor() {
  if (speedTimer) window.clearInterval(speedTimer)
  speedTimer = null
}

// ===== 进度条拖动/点击跳转 =====
const progressBarRef = ref<HTMLElement | null>(null)
function seekFromBar(e: MouseEvent | TouchEvent) {
  const bar = progressBarRef.value
  const p = player.value
  if (!bar || !p || !duration.value) return
  const rect = bar.getBoundingClientRect()
  const clientX = 'touches' in e ? (e as TouchEvent).touches[0].clientX : (e as MouseEvent).clientX
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
  p.currentTime = ratio * duration.value
}
function formatTime(s: number): string {
  if (!s || isNaN(s)) return '00:00'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  if (h > 0) return `${h}:${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
  return `${m.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
}
function formatSpeed(kbps: number): string {
  if (kbps >= 1024) return (kbps / 1024).toFixed(1) + ' MB'
  return Math.round(kbps) + ' KB'
}

// ===== 全屏 =====
const isFullscreen = ref(false)
function toggleFullscreen() {
  const el = player.value
  if (!el) return
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
  else el.requestFullscreen?.().catch(() => {})
}
function onFsChange() {
  isFullscreen.value = !!document.fullscreenElement
  // 竖屏内横屏全屏退出时，把 video 还原回 portrait-item
  if (!isFullscreen.value && mode.value === 'portrait' && portraitFsWrapper.value) {
    requestAnimationFrame(() => restorePortraitVideo())
  }
}

// ===== 移动端手势：双击暂停 / 左右滑动快进 =====
const isMobile = ref(false)
const isTouchMode = computed(() => isMobile.value && mode.value === 'normal')
const SEEK_SENSITIVITY = 0.4
const touchStartX = ref(0)
const touchStartY = ref(0)
const touchStartCurrent = ref(0)
const touchMoved = ref(false)
const lastTapTime = ref(0)
let tapTimer: number | null = null
const seekFeedbackVisible = ref(false)
const seekFeedbackText = ref('')
let seekFeedbackTimer: number | null = null

function onGestureStart(e: TouchEvent) {
  const t = e.touches[0]
  if (!t) return
  touchStartX.value = t.clientX
  touchStartY.value = t.clientY
  touchStartCurrent.value = player.value?.currentTime || 0
  touchMoved.value = false
}
function onGestureMove(e: TouchEvent) {
  if (!player.value) return
  const t = e.touches[0]
  if (!t) return
  const dx = t.clientX - touchStartX.value
  const dy = t.clientY - touchStartY.value
  if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return
  if (Math.abs(dx) > Math.abs(dy)) {
    touchMoved.value = true
    const ratio = dx / window.innerWidth
    const delta = ratio * duration.value * SEEK_SENSITIVITY
    const target = Math.max(0, Math.min(duration.value, touchStartCurrent.value + delta))
    player.value.currentTime = target
    seekFeedbackText.value = `${delta >= 0 ? '快进' : '快退'} ${Math.abs(Math.round(delta))} 秒`
    seekFeedbackVisible.value = true
    if (seekFeedbackTimer) clearTimeout(seekFeedbackTimer)
  } else {
    touchMoved.value = true
  }
}
function onGestureEnd() {
  if (touchMoved.value) {
    if (seekFeedbackTimer) clearTimeout(seekFeedbackTimer)
    seekFeedbackTimer = window.setTimeout(() => { seekFeedbackVisible.value = false }, 500)
    touchMoved.value = false
    return
  }
  const now = Date.now()
  if (now - lastTapTime.value < 300) {
    if (tapTimer) { clearTimeout(tapTimer); tapTimer = null }
    togglePlay()
    lastTapTime.value = 0
  } else {
    lastTapTime.value = now
    if (tapTimer) clearTimeout(tapTimer)
    tapTimer = window.setTimeout(() => {
      showControls.value = !showControls.value
      if (showControls.value && isPlaying.value) {
        controlsTimer = window.setTimeout(() => {
          if (isPlaying.value && !isBuffering.value) showControls.value = false
        }, 3000)
      }
      tapTimer = null
    }, 280)
  }
}

// ===== 竖屏模式（抖音式纵向 feed · 完整互动 UI） =====
const portraitDragY = ref(0)
const portraitDragging = ref(false)
const portraitTransition = ref(false)
const portraitViewportH = ref(0)
const portraitSwitching = ref(false)
const PORTRAIT_CUR = 1
const slotPlayers = ref<(HTMLVideoElement | null)[]>([null, null, null])
const slotTimes = ref<{ current: number; duration: number }[]>([{ current: 0, duration: 0 }, { current: 0, duration: 0 }, { current: 0, duration: 0 }])
const portraitPlaying = ref(true)
let portraitBodyScrollY = 0
const portraitBuffering = ref(false)

// 竖屏互动状态
const portraitUiVisible = ref(true)
let portraitUiHideTimer: number | null = null
const PORTRAIT_UI_HIDE_DELAY = 3000
const portraitMoreOpen = ref(false)
const showPortraitDoubleLike = ref(false)
let doubleLikeTimer: number | null = null
let portraitTapTimer: number | null = null
const portraitLastTap = ref(0)
const portraitFsWrapper = ref<HTMLDivElement | null>(null)
const portraitFsOriginalParent = ref<Element | null>(null)

// 当前竖屏项（来自 playlist[curIndex]，含互动状态）
const portraitCurrent = computed<PlayItem | null>(() => props.playlist[curIndex.value] || null)
const portraitLikeActive = computed(() => !!portraitCurrent.value?.is_liked)
const portraitFavoriteActive = computed(() => !!portraitCurrent.value?.is_favorited)
const portraitDislikeActive = computed(() => !!portraitCurrent.value?.is_disliked)
const portraitLikeCount = computed(() => portraitCurrent.value?.like_count || 0)
const portraitFavoriteCount = computed(() => portraitCurrent.value?.favorite_count || 0)

// 三格：[prev, current, next]
const portraitSlots = computed(() => {
  const make = (i: number) => props.playlist[i] || null
  return [make(curIndex.value - 1), make(curIndex.value), make(curIndex.value + 1)]
})

function setSlotPlayer(i: number, el: any) {
  if (el) slotPlayers.value[i] = el as HTMLVideoElement
}
const portraitTrackY = computed(() => -portraitViewportH.value + portraitDragY.value)

let portraitTouchStartY = 0
const PORTRAIT_SWIPE_THRESHOLD = 60
function onPortraitTouchStart(e: TouchEvent) {
  const t = e.touches[0]
  if (!t) return
  portraitTouchStartY = t.clientY
  portraitViewportH.value = window.innerHeight
  portraitDragging.value = true
  portraitTransition.value = false
}
function onPortraitTouchMove(e: TouchEvent) {
  if (!portraitDragging.value || portraitSwitching.value) return
  const t = e.touches[0]
  if (!t) return
  const dy = t.clientY - portraitTouchStartY
  portraitDragY.value = dy
}
async function onPortraitTouchEnd() {
  if (!portraitDragging.value) return
  if (portraitSwitching.value) { portraitDragging.value = false; return }
  portraitDragging.value = false
  const dy = portraitDragY.value
  portraitTransition.value = true
  if (Math.abs(dy) < PORTRAIT_SWIPE_THRESHOLD) {
    portraitDragY.value = 0
    setTimeout(() => { portraitTransition.value = false }, 250)
    return
  }
  const goNext = dy < 0
  if (goNext) {
    await goPortraitNext()
  } else {
    goPortraitPrev()
  }
}
// 上滑下一个：优先切到列表内下一项；列表已到末尾则尝试 loadMore 回调
async function goPortraitNext() {
  portraitSwitching.value = true
  portraitDragY.value = -portraitViewportH.value
  await new Promise((r) => setTimeout(r, 280))
  let ok = curIndex.value + 1 < props.playlist.length
  if (!ok && typeof props.loadMore === 'function') {
    let added: PlayItem | null | undefined = null
    try {
      added = await props.loadMore(portraitCurrent.value || { src: '' })
    } catch { /* ignore */ }
    if (added && added.src) props.playlist.push(added)
    ok = curIndex.value + 1 < props.playlist.length
  }
  if (ok) {
    curIndex.value += 1
    emit('update:index', curIndex.value)
  }
  portraitTransition.value = false
  portraitDragY.value = 0
  portraitSwitching.value = false
  afterPortraitSwitch()
}
function goPortraitPrev() {
  if (curIndex.value <= 0) {
    portraitTransition.value = true
    portraitDragY.value = 0
    setTimeout(() => { portraitTransition.value = false }, 250)
    return
  }
  portraitSwitching.value = true
  portraitDragY.value = portraitViewportH.value
  setTimeout(() => {
    curIndex.value -= 1
    emit('update:index', curIndex.value)
    portraitTransition.value = false
    portraitDragY.value = 0
    portraitSwitching.value = false
    afterPortraitSwitch()
  }, 280)
}
// 预加载下一个视频到 playlist，使 slot 2 提前持有 src，滑动切换时无缝衔接
async function prefetchNext() {
  if (curIndex.value + 1 < props.playlist.length) return
  if (typeof props.loadMore !== 'function') return
  try {
    const added = await props.loadMore(portraitCurrent.value || { src: '' })
    if (added && added.src) props.playlist.push(added)
  } catch { /* ignore */ }
}
function afterPortraitSwitch() {
  showPortraitUi()
  prefetchNext()
  nextTick(() => {
    const cur = slotPlayers.value[PORTRAIT_CUR]
    if (cur) {
      // 切换 / 自动连播时 play() 多在用户手势之外触发；未静音的自动播放会被移动端浏览器
      // （iOS Safari 等）的自动播放策略拦截，于是新视频停在预览图不动。
      // 先以静音播放（静音自动播放始终被允许），待播放真正开始后取消静音，
      // 既保证一定能播，又保留有声观感，且不依赖手势时机。
      cur.muted = true
      const p = cur.play()
      if (p && typeof p.then === 'function') {
        p.then(() => { cur.muted = false }).catch(() => { cur.muted = false })
      } else {
        cur.muted = false
      }
    }
    slotPlayers.value[2]?.pause()
    slotPlayers.value[0]?.pause()
  })
}
function onPortraitMeta(i: number) {
  const v = slotPlayers.value[i]
  if (!v) return
  if (v.duration && !isNaN(v.duration)) slotTimes.value[i].duration = v.duration
}
function onPortraitTimeUpdate(i: number) {
  const v = slotPlayers.value[i]
  if (!v) return
  slotTimes.value[i].current = v.currentTime
}
function onPortraitSeek(e: MouseEvent | TouchEvent, i: number) {
  const bar = e.currentTarget as HTMLElement
  const v = slotPlayers.value[i]
  if (!bar || !v) return
  const rect = bar.getBoundingClientRect()
  const clientX = 'touches' in e ? (e as TouchEvent).touches[0]?.clientX : (e as MouseEvent).clientX
  if (clientX == null) return
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  const dur = Number(v.duration) || (slotTimes.value[i]?.duration || 0)
  v.currentTime = ratio * dur
  if (slotTimes.value[i]) slotTimes.value[i].current = ratio * dur
}
function togglePortraitPlay() {
  const v = slotPlayers.value[PORTRAIT_CUR]
  if (!v) return
  if (v.paused) v.play().catch(() => {})
  else v.pause()
}
function onPortraitPlay() { portraitPlaying.value = true; showPortraitUi() }
function onPortraitPause() { portraitPlaying.value = false; portraitUiVisible.value = true; if (portraitUiHideTimer) window.clearTimeout(portraitUiHideTimer) }
function onPortraitWaiting() { portraitBuffering.value = true }
function onPortraitPlaying() { portraitBuffering.value = false }
function onPortraitEnded() {
  if (portraitSwitching.value) return
  goPortraitNext()
}
// 单击切控件显隐 / 双击点赞
function onPortraitTap() {
  if (portraitMoreOpen.value) { portraitMoreOpen.value = false; return }
  const now = Date.now()
  if (now - portraitLastTap.value < 300) {
    portraitLastTap.value = 0
    if (portraitTapTimer) { clearTimeout(portraitTapTimer); portraitTapTimer = null }
    if (props.portraitInteractions) {
      if (!portraitLikeActive.value) emit('like', portraitCurrent.value || { src: '' })
      showPortraitDoubleLike.value = true
      if (doubleLikeTimer) clearTimeout(doubleLikeTimer)
      doubleLikeTimer = window.setTimeout(() => { showPortraitDoubleLike.value = false }, 700)
    }
  } else {
    portraitLastTap.value = now
    if (portraitTapTimer) clearTimeout(portraitTapTimer)
    portraitTapTimer = window.setTimeout(() => {
      if (portraitUiVisible.value) hidePortraitUi()
      else showPortraitUi()
      portraitTapTimer = null
    }, 300)
  }
}
function showPortraitUi() {
  portraitUiVisible.value = true
  if (portraitMoreOpen.value) portraitMoreOpen.value = false
  if (portraitUiHideTimer) window.clearTimeout(portraitUiHideTimer)
  portraitUiHideTimer = window.setTimeout(() => {
    if (portraitPlaying.value && !portraitMoreOpen.value) portraitUiVisible.value = false
  }, PORTRAIT_UI_HIDE_DELAY)
}
function hidePortraitUi() {
  if (portraitMoreOpen.value) return
  portraitUiVisible.value = false
  if (portraitUiHideTimer) window.clearTimeout(portraitUiHideTimer)
}
function togglePortraitMore() { portraitMoreOpen.value = !portraitMoreOpen.value }
function closePortraitMore() { portraitMoreOpen.value = false }

function enterPortraitMode() {
  if (!props.enablePortrait || props.playlist.length === 0) return
  mode.value = 'portrait'
  portraitDragY.value = 0
  portraitBuffering.value = false
  portraitViewportH.value = window.innerHeight
  portraitBodyScrollY = window.scrollY
  showPortraitUi()
  document.body.style.position = 'fixed'
  document.body.style.top = `-${portraitBodyScrollY}px`
  document.body.style.left = '0'
  document.body.style.right = '0'
  document.body.style.width = '100%'
  document.body.style.overflow = 'hidden'
  document.body.classList.add('portrait-mode-active')
  nextTick(() => {
    const cur = slotPlayers.value[PORTRAIT_CUR]
    if (cur) { cur.muted = false; cur.play().catch(() => {}) }
  })
  prefetchNext()
}
function exitPortraitMode() {
  mode.value = 'normal'
  portraitMoreOpen.value = false
  document.body.classList.remove('portrait-mode-active')
  document.body.style.position = ''
  document.body.style.top = ''
  document.body.style.left = ''
  document.body.style.right = ''
  document.body.style.width = ''
  document.body.style.overflow = ''
  if (portraitBodyScrollY) window.scrollTo(0, portraitBodyScrollY)
}
// 竖屏横屏全屏：把 video 移入 body 临时 wrapper 再请求原生全屏，退出后还原
function enterLandscapeFromPortrait() {
  emit('toggle-landscape', portraitCurrent.value || { src: '' })
  const el = slotPlayers.value[PORTRAIT_CUR]
  if (!el || !el.requestFullscreen) { el?.parentElement?.requestFullscreen?.().catch(() => {}); return }
  const wrapper = document.createElement('div')
  wrapper.className = 'portrait-fs-wrapper'
  portraitFsOriginalParent.value = el.parentElement
  wrapper.appendChild(el)
  document.body.appendChild(wrapper)
  portraitFsWrapper.value = wrapper
  el.requestFullscreen().catch(() => { restorePortraitVideo() })
}
function restorePortraitVideo() {
  const wrapper = portraitFsWrapper.value
  const origParent = portraitFsOriginalParent.value
  if (wrapper) {
    const video = wrapper.querySelector('video') as HTMLVideoElement | null
    if (video) {
      let target: Element | null = origParent
      if (target && !target.isConnected) {
        const slotEl = slotPlayers.value[PORTRAIT_CUR]
        target = slotEl ? slotEl.parentElement : null
      }
      if (target && target.isConnected) target.appendChild(video)
      else document.body.appendChild(video)
    }
    wrapper.remove()
  }
  portraitFsWrapper.value = null
  portraitFsOriginalParent.value = null
}

// 监听 playlist / initialIndex 变化
watch(
  () => props.initialIndex,
  (v) => { curIndex.value = Math.max(0, Math.min(v, props.playlist.length - 1)) }
)

// 切换视频源时重置状态
watch(curIndex, () => {
  isPlaying.value = false
  isBuffering.value = false
  netSpeed.value = 0
  currentTime.value = 0
  duration.value = 0
  if (mode.value === 'normal' && props.autoplay) {
    nextTick(() => player.value?.play().catch(() => {}))
  }
})

function detectMobile() {
  isMobile.value = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent)
}
detectMobile()

onBeforeUnmount(() => {
  if (controlsTimer) window.clearTimeout(controlsTimer)
  if (speedTimer) window.clearInterval(speedTimer)
  if (tapTimer) window.clearTimeout(tapTimer)
  if (seekFeedbackTimer) window.clearTimeout(seekFeedbackTimer)
  if (portraitUiHideTimer) window.clearTimeout(portraitUiHideTimer)
  if (doubleLikeTimer) window.clearTimeout(doubleLikeTimer)
  if (portraitTapTimer) window.clearTimeout(portraitTapTimer)
  restorePortraitVideo()
  document.removeEventListener('fullscreenchange', onFsChange)
  if (mode.value === 'portrait') exitPortraitMode()
})
document.addEventListener('fullscreenchange', onFsChange)
</script>

<template>
  <div class="video-player" :class="{ 'is-fullscreen': isFullscreen, 'mode-portrait': mode === 'portrait' }">
    <template v-if="mode === 'normal'">
      <video
        ref="player"
        :src="currentItem?.src"
        :poster="currentItem?.poster"
        class="video-el"
        playsinline
        webkit-playsinline
        x5-playsinline
        x5-video-player-type="h5-page"
        x5-video-player-fullscreen="true"
        :controls="!isMobile"
        preload="metadata"
        :autoplay="autoplay"
        @play="onPlay"
        @pause="onPause"
        @seeked="onTimeUpdate"
        @timeupdate="onTimeUpdate"
        @loadedmetadata="onLoadedMetadata"
        @waiting="onWaiting"
        @playing="onPlaying"
        @ended="onEnded"
        @dblclick="toggleFullscreen"
      ></video>

      <!-- 缓冲转圈 + 网速 -->
      <div v-if="isBuffering" class="buffering-overlay">
        <div class="buffering-spinner"></div>
        <div class="buffering-speed" v-if="netSpeed > 0">{{ formatSpeed(netSpeed) }}/s</div>
      </div>

      <!-- 移动端手势层 -->
      <div
        v-if="isTouchMode"
        class="gesture-layer"
        @touchstart="onGestureStart"
        @touchmove.prevent="onGestureMove"
        @touchend="onGestureEnd"
      ></div>
      <div v-if="isTouchMode && seekFeedbackVisible" class="seek-feedback">{{ seekFeedbackText }}</div>

      <!-- 移动端控制栏 -->
      <div v-if="isMobile" class="mobile-controls" :class="{ hidden: !showControls }" @click.stop>
        <div ref="progressBarRef" class="mp-bar" @touchstart.prevent="seekFromBar($event)" @touchmove.prevent="seekFromBar($event)" @click="seekFromBar($event)">
          <div class="mp-played" :style="{ width: (duration ? (currentTime / duration) * 100 : 0) + '%' }"></div>
          <div class="mp-thumb" :style="{ left: (duration ? (currentTime / duration) * 100 : 0) + '%' }"></div>
        </div>
        <div class="mc-row">
          <button class="mc-btn" @click.stop="togglePlay" :aria-label="isPlaying ? '暂停' : '播放'">
            <svg v-if="!isPlaying" width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
            <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M6 5h4v14H6zM14 5h4v14h-4z" /></svg>
          </button>
          <div class="mp-time"><span>{{ formatTime(currentTime) }}</span><span>{{ formatTime(duration) }}</span></div>
          <button class="mc-btn" @click.stop="toggleFullscreen" :aria-label="isFullscreen ? '退出全屏' : '全屏'">
            <svg v-if="!isFullscreen" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 0 0 1 2 2v3M8 21H5a2 0 0 1-2-2v-3M16 21h3a2 0 0 0 2-2v-3" /></svg>
            <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3v3a2 0 0 1-2 2H3M21 8h-3a2 0 0 1-2-2V3M3 16h3a2 0 0 1 2 2v3M16 21v-3a2 0 0 1 2-2h3" /></svg>
          </button>
          <button v-if="enablePortrait" class="mc-btn" @click.stop="enterPortraitMode" aria-label="竖屏全屏" title="竖屏全屏">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="7" y="2" width="10" height="20" rx="2" /><line x1="11" y1="18" x2="13" y2="18" /></svg>
          </button>
        </div>
      </div>

      <!-- PC 端竖屏入口 -->
      <button v-if="!isMobile && enablePortrait" class="portrait-entry-pc" @click="enterPortraitMode" title="竖屏全屏" aria-label="竖屏全屏">竖屏</button>
    </template>

    <!-- 竖屏沉浸模式：Teleport 到 body 避免裁剪 -->
    <Teleport to="body">
      <div class="portrait-mode" v-if="mode === 'portrait'" @click="onPortraitTap">
        <div
          class="portrait-track"
          :class="{ dragging: portraitDragging, animating: portraitTransition }"
          :style="{ transform: `translateY(${portraitTrackY}px)` }"
          @touchstart="onPortraitTouchStart"
          @touchmove.prevent="onPortraitTouchMove"
          @touchend="onPortraitTouchEnd"
        >
          <div v-for="(item, i) in portraitSlots" :key="i" class="portrait-item">
            <template v-if="item">
              <video
                :ref="(el) => setSlotPlayer(i, el)"
                :src="item.src"
                :poster="item.poster"
                class="portrait-video"
                playsinline
                webkit-playsinline
                x5-playsinline
                x5-video-player-type="h5-page"
                preload="auto"
                :autoplay="i === PORTRAIT_CUR"
                :muted="i !== PORTRAIT_CUR"
                @play="() => { if (i === PORTRAIT_CUR) onPortraitPlay() }"
                @pause="() => { if (i === PORTRAIT_CUR) onPortraitPause() }"
                @timeupdate="() => onPortraitTimeUpdate(i)"
                @loadedmetadata="() => onPortraitMeta(i)"
                @durationchange="() => onPortraitMeta(i)"
                @waiting="() => { if (i === PORTRAIT_CUR) onPortraitWaiting() }"
                @playing="() => { if (i === PORTRAIT_CUR) onPortraitPlaying() }"
                @ended="() => { if (i === PORTRAIT_CUR) onPortraitEnded() }"
                @click.stop="onPortraitTap"
              ></video>

              <!-- 仅当前槽渲染控制层：作为轨道子节点随 translateY 一起滑动 -->
              <template v-if="i === PORTRAIT_CUR && props.portraitInteractions">
                <!-- 右侧竖排操作栏：点赞 / 收藏 -->
                <div class="portrait-actions" :class="{ 'ui-hidden': !portraitUiVisible }" @touchstart.stop>
                  <button class="portrait-action" :class="{ active: portraitLikeActive }" @click.stop="emit('like', item)" aria-label="点赞">
                    <span class="portrait-action-icon">
                      <svg width="30" height="30" viewBox="0 0 24 24" :fill="portraitLikeActive ? '#ff2d55' : 'none'" stroke="currentColor" stroke-width="2">
                        <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
                      </svg>
                    </span>
                    <span class="portrait-action-count">{{ portraitLikeCount }}</span>
                  </button>
                  <button class="portrait-action" :class="{ active: portraitFavoriteActive }" @click.stop="emit('favorite', item)" aria-label="收藏">
                    <span class="portrait-action-icon">
                      <svg width="30" height="30" viewBox="0 0 24 24" :fill="portraitFavoriteActive ? '#ffd60a' : 'none'" stroke="currentColor" stroke-width="2">
                        <path d="M12 17.3l-6.2 3.7 1.6-7L2 9.2l7.1-.6L12 2l2.9 6.6 7.1.6-5.4 4.8 1.6 7z" />
                      </svg>
                    </span>
                    <span class="portrait-action-count">{{ portraitFavoriteCount }}</span>
                  </button>
                </div>

                <!-- 底部控制栏：标题 / 进度条 / 播放·全屏·详情 -->
                <div class="portrait-bottom-bar" :class="{ 'ui-hidden': !portraitUiVisible }" @touchstart.stop>
                  <div class="pb-title">
                    <span class="pb-title-text">{{ item.title || '视频' }}</span>
                  </div>
                  <div class="pb-progress" @touchstart.stop.prevent="onPortraitSeek($event, i)" @touchmove.stop.prevent="onPortraitSeek($event, i)" @click.stop="onPortraitSeek($event, i)">
                    <div class="pp-track">
                      <div class="pp-played" :style="{ width: ((slotTimes[i].duration || 0) ? (slotTimes[i].current / slotTimes[i].duration) * 100 : 0) + '%' }"></div>
                      <div class="pp-thumb" :style="{ left: ((slotTimes[i].duration || 0) ? (slotTimes[i].current / slotTimes[i].duration) * 100 : 0) + '%' }"></div>
                    </div>
                    <div class="pp-time">{{ formatTime(slotTimes[i].current) }} / {{ formatTime(slotTimes[i].duration) }}</div>
                  </div>
                  <div class="pb-buttons">
                    <button class="pb-btn" @click.stop="togglePortraitPlay" :aria-label="portraitPlaying ? '暂停' : '播放'">
                      <svg v-if="portraitPlaying" width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                        <rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" />
                      </svg>
                      <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z" /></svg>
                    </button>
                    <div class="pb-right">
                      <button class="pb-btn" @click.stop="enterLandscapeFromPortrait" aria-label="横屏全屏" title="横屏全屏">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3" />
                        </svg>
                      </button>
                      <button class="pb-btn" @click.stop="emit('open-detail', item)" aria-label="详情" title="详情模式">
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <rect x="3" y="4" width="18" height="16" rx="2" /><line x1="3" y1="9" x2="21" y2="9" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </div>
              </template>
            </template>
          </div>
        </div>

        <!-- 双击爱心动画 -->
        <transition name="heart-pop">
          <div v-if="showPortraitDoubleLike" class="portrait-heart">
            <svg width="80" height="80" viewBox="0 0 24 24" fill="#ff2d55">
              <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z" />
            </svg>
          </div>
        </transition>

        <!-- 右上角：更多（收纳不喜欢等） -->
        <div v-if="props.portraitInteractions" class="portrait-more" :class="{ 'ui-hidden': !portraitUiVisible }">
          <button class="portrait-top-btn" @click.stop="togglePortraitMore" aria-label="更多">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
              <circle cx="12" cy="5" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="12" cy="19" r="2" />
            </svg>
          </button>
          <div v-if="portraitMoreOpen" class="portrait-more-menu" @click.stop>
            <button class="portrait-more-item" :class="{ active: portraitDislikeActive }" @click.stop="emit('dislike', portraitCurrent || { src: '' }); closePortraitMore()" aria-label="不喜欢">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="9" /><line x1="8" y1="8" x2="16" y2="16" /><line x1="16" y1="8" x2="8" y2="16" />
              </svg>
              <span>不喜欢</span>
            </button>
          </div>
        </div>

        <!-- 左上角：退出（←） -->
        <button class="portrait-back-btn" :class="{ 'ui-hidden': !portraitUiVisible }" @click.stop="exitPortraitMode" aria-label="退出竖屏">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
            <line x1="19" y1="12" x2="5" y2="12" /><polyline points="12 19 5 12 12 5" />
          </svg>
        </button>

        <!-- 轻量缓冲指示 -->
        <div v-if="portraitBuffering && !portraitDragging" class="portrait-buffering">
          <div class="buffering-spinner"></div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.video-player {
  position: relative;
  width: 100%;
  background: #000;
  border-radius: 10px;
  overflow: hidden;
}
.video-el {
  display: block;
  width: 100%;
  max-height: 80vh;
  background: #000;
}
.video-player.is-fullscreen .video-el { max-height: 100vh; }

/* 缓冲 */
.buffering-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  background: rgba(0, 0, 0, 0.25);
  pointer-events: none;
}
.buffering-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: vp-spin 0.8s linear infinite;
}
.buffering-speed { color: #fff; font-size: 12px; }
@keyframes vp-spin { to { transform: rotate(360deg); } }

/* 手势层 */
.gesture-layer { position: absolute; inset: 0; z-index: 5; touch-action: none; }
.seek-feedback {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 14px;
  z-index: 8;
  pointer-events: none;
}

/* 移动端控制栏 */
.mobile-controls {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 8px 10px 10px;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.6));
  z-index: 6;
  transition: opacity 0.25s;
}
.mobile-controls.hidden { opacity: 0; pointer-events: none; }
.mp-bar {
  position: relative;
  height: 4px;
  background: rgba(255, 255, 255, 0.3);
  border-radius: 2px;
  margin-bottom: 8px;
}
.mp-played { position: absolute; left: 0; top: 0; height: 100%; background: var(--accent); border-radius: 2px; }
.mp-thumb {
  position: absolute;
  top: 50%;
  width: 12px;
  height: 12px;
  background: #fff;
  border-radius: 50%;
  transform: translate(-50%, -50%);
}
.mc-row { display: flex; align-items: center; gap: 12px; }
.mc-btn { background: none; border: none; color: #fff; cursor: pointer; padding: 0; display: flex; align-items: center; }
.mp-time { color: #fff; font-size: 12px; display: flex; gap: 6px; margin-left: auto; }

.portrait-entry-pc {
  position: absolute;
  top: 8px;
  right: 8px;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  border: none;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
  z-index: 7;
}

/* 竖屏沉浸 */
.portrait-mode {
  position: fixed;
  inset: 0;
  background: #000;
  z-index: 2000;
  overflow: hidden;
}
.portrait-track {
  position: absolute;
  left: 0;
  right: 0;
  top: 0;
  height: 300vh;
  transition: none;
}
.portrait-track.animating { transition: transform 0.25s ease-out; }
.portrait-track.dragging { transition: none; }
.portrait-item {
  position: absolute;
  left: 0;
  right: 0;
  width: 100%;
  height: 100vh;
  top: 0;
}
.portrait-item:nth-child(1) { transform: translateY(0); }
.portrait-item:nth-child(2) { transform: translateY(100vh); }
.portrait-item:nth-child(3) { transform: translateY(200vh); }
.portrait-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000;
}
/* 双击爱心 */
.portrait-heart {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 5;
  pointer-events: none;
  filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.5));
}
.heart-pop-enter-active { animation: heart-pop 0.7s ease-out; }
@keyframes heart-pop {
  0% { transform: translate(-50%, -50%) scale(0.3); opacity: 0; }
  30% { transform: translate(-50%, -50%) scale(1.2); opacity: 1; }
  70% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
  100% { transform: translate(-50%, -50%) scale(1.4); opacity: 0; }
}
/* 右上角更多 */
.portrait-more {
  position: absolute;
  top: max(12px, env(safe-area-inset-top));
  right: 12px;
  z-index: 11;
}
.portrait-more-menu {
  position: absolute;
  top: 48px;
  right: 0;
  min-width: 112px;
  padding: 6px;
  border-radius: 12px;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(8px);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.portrait-more-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 10px;
  border: none;
  border-radius: 8px;
  background: none;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  white-space: nowrap;
}
.portrait-more-item:active { background: rgba(255, 255, 255, 0.12); }
.portrait-more-item.active { color: #cfcfcf; }
/* 底部控制栏 */
.portrait-bottom-bar {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: calc(max(16px, env(safe-area-inset-bottom)));
  z-index: 14;
  display: flex;
  flex-direction: column;
  gap: 4px;
  pointer-events: none;
  transition: opacity 0.25s ease;
}
.portrait-bottom-bar > * { pointer-events: auto; }
.portrait-bottom-bar.ui-hidden { opacity: 0; pointer-events: none; }
.pb-title {
  color: #fff;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.85);
  font-size: 14px;
  line-height: 1.35;
}
.pb-title-text { font-weight: 600; }
.pb-meta {
  display: block;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.75);
  margin-top: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pb-progress { width: 100%; }
.pb-progress .pp-track {
  position: relative;
  height: 3px;
  background: rgba(255, 255, 255, 0.35);
  border-radius: 3px;
}
.pb-progress .pp-played {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  background: #ff2d55;
  border-radius: 3px;
}
.pb-progress .pp-thumb {
  position: absolute;
  top: 50%;
  width: 13px;
  height: 13px;
  background: #fff;
  border-radius: 50%;
  transform: translate(-50%, -50%);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.4);
}
.pb-progress .pp-time {
  margin-top: 2px;
  font-size: 11px;
  color: #fff;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
}
.pb-buttons {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.pb-right { display: flex; align-items: center; gap: 10px; }
.pb-btn {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  backdrop-filter: blur(4px);
}
.pb-btn:active { background: rgba(0, 0, 0, 0.7); }
/* 右侧竖排操作栏 */
.portrait-actions {
  position: absolute;
  right: 14px;
  bottom: 124px;
  z-index: 13;
  display: flex;
  flex-direction: column;
  gap: 14px;
  align-items: center;
  transition: opacity 0.25s ease;
}
.portrait-actions.ui-hidden { opacity: 0; pointer-events: none; }
.portrait-action {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  background: none;
  border: none;
  color: #fff;
  cursor: pointer;
}
.portrait-action-icon {
  width: 38px;
  height: 38px;
  border-radius: 50%;
  background: none;
  display: flex;
  align-items: center;
  justify-content: center;
  filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.6));
  transition: transform 0.15s, background 0.2s;
}
.portrait-action:active .portrait-action-icon { transform: scale(0.9); }
.portrait-action.active { color: #ff2d55; }
.portrait-action:nth-child(2).active { color: #ffd60a; }
.portrait-action-count {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
}
.portrait-more,
.portrait-back-btn { transition: opacity 0.25s ease; }
.portrait-more.ui-hidden,
.portrait-back-btn.ui-hidden { opacity: 0; pointer-events: none; }
.portrait-top-btn {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  cursor: pointer;
  backdrop-filter: blur(4px);
}
.portrait-top-btn:active { background: rgba(0, 0, 0, 0.7); }
/* 左上角退出箭头 */
.portrait-back-btn {
  position: absolute;
  top: max(12px, env(safe-area-inset-top));
  left: 12px;
  z-index: 10;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  border: none;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  backdrop-filter: blur(4px);
}
.portrait-back-btn:active { background: rgba(0, 0, 0, 0.7); }
/* 轻量缓冲 */
.portrait-buffering {
  position: absolute;
  inset: 0;
  z-index: 8;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.portrait-fs-wrapper {
  width: 100vw;
  height: 100vh;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
}
.portrait-fs-wrapper video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.portrait-edge-hint {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: rgba(255, 255, 255, 0.7);
  font-size: 14px;
  z-index: 9;
  pointer-events: none;
}
.buffering-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid rgba(255, 255, 255, 0.25);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
</style>
