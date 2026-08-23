<script setup lang="ts">
import { ref, computed, watch, onBeforeUnmount, nextTick } from 'vue'

interface PlayItem {
  src: string
  poster?: string
  title?: string
}

const props = withDefaults(
  defineProps<{
    playlist: PlayItem[] // 视频列表（按播放顺序）；单视频时长度为 1
    initialIndex?: number
    autoplay?: boolean
  }>(),
  { initialIndex: 0, autoplay: false }
)

const emit = defineEmits<{
  (e: 'update:index', index: number): void
  (e: 'ended', index: number): void
  (e: 'play', currentTime: number): void
  (e: 'pause', currentTime: number): void
  (e: 'timeupdate', currentTime: number): void
  (e: 'seeked', currentTime: number): void
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

// ===== 竖屏模式（抖音式纵向 feed） =====
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

// 三格：[prev, current, next]
const portraitSlots = computed(() => {
  const make = (i: number) => props.playlist[i] || null
  const prev = curIndex.value - 1
  const next = curIndex.value + 1
  return [make(prev), make(curIndex.value), make(next)]
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
  // 边界阻尼：第一格上滑 / 最后一格下滑 不跟手（停住）
  const atTop = curIndex.value === 0 && dy > 0
  const atBottom = curIndex.value === props.playlist.length - 1 && dy < 0
  if (atTop || atBottom) {
    portraitDragY.value = dy * 0.25
  } else {
    portraitDragY.value = dy
  }
}
function onPortraitTouchEnd() {
  if (!portraitDragging.value) return
  portraitDragging.value = false
  const dy = portraitDragY.value
  if (Math.abs(dy) < PORTRAIT_SWIPE_THRESHOLD) {
    // 回弹
    portraitTransition.value = true
    portraitDragY.value = 0
    setTimeout(() => { portraitTransition.value = false }, 250)
    return
  }
  // 切换：上滑→下一个，下滑→上一个
  const goNext = dy < 0
  const target = goNext ? curIndex.value + 1 : curIndex.value - 1
  if (target < 0 || target >= props.playlist.length) {
    // 边界，回弹停住
    portraitTransition.value = true
    portraitDragY.value = 0
    setTimeout(() => { portraitTransition.value = false }, 250)
    return
  }
  portraitSwitching.value = true
  portraitTransition.value = true
  portraitDragY.value = 0
  curIndex.value = target
  emit('update:index', target)
  setTimeout(() => {
    portraitSwitching.value = false
    portraitTransition.value = false
  }, 260)
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
function onPortraitTap() {
  showPortraitUiTemporarily()
}
function showPortraitUiTemporarily() {
  showControls.value = true
  if (controlsTimer) window.clearTimeout(controlsTimer)
  controlsTimer = window.setTimeout(() => {
    if (portraitPlaying.value) showControls.value = false
  }, 3000)
}

function enterPortraitMode() {
  if (props.playlist.length === 0) return
  mode.value = 'portrait'
  portraitDragY.value = 0
  portraitViewportH.value = window.innerHeight
  portraitBodyScrollY = window.scrollY
  document.body.style.position = 'fixed'
  document.body.style.top = `-${portraitBodyScrollY}px`
  document.body.style.left = '0'
  document.body.style.right = '0'
  document.body.style.width = '100%'
  document.body.style.overflow = 'hidden'
  document.body.classList.add('portrait-mode-active')
  nextTick(() => {
    const cur = slotPlayers.value[PORTRAIT_CUR]
    if (cur) cur.play().catch(() => {})
  })
}
function exitPortraitMode() {
  mode.value = 'normal'
  document.body.classList.remove('portrait-mode-active')
  document.body.style.position = ''
  document.body.style.top = ''
  document.body.style.left = ''
  document.body.style.right = ''
  document.body.style.width = ''
  document.body.style.overflow = ''
  if (portraitBodyScrollY) window.scrollTo(0, portraitBodyScrollY)
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
          <button class="mc-btn" @click.stop="enterPortraitMode" aria-label="竖屏全屏" title="竖屏全屏">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="7" y="2" width="10" height="20" rx="2" /><line x1="11" y1="18" x2="13" y2="18" /></svg>
          </button>
        </div>
      </div>

      <!-- PC 端竖屏入口 -->
      <button v-if="!isMobile" class="portrait-entry-pc" @click="enterPortraitMode" title="竖屏全屏" aria-label="竖屏全屏">竖屏</button>
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
                loop
                :muted="i !== PORTRAIT_CUR"
                @play="() => { if (i === PORTRAIT_CUR) portraitPlaying = true }"
                @pause="() => { if (i === PORTRAIT_CUR) portraitPlaying = false }"
                @timeupdate="() => onPortraitTimeUpdate(i)"
                @loadedmetadata="() => onPortraitMeta(i)"
                @durationchange="() => onPortraitMeta(i)"
                @click.stop="onPortraitTap"
              ></video>
              <div class="portrait-bottom-bar" :class="{ 'ui-hidden': !showControls }" @touchstart.stop>
                <div class="pb-title"><span class="pb-title-text">{{ item.title || ('视频 ' + (curIndex - 1 + i + 1)) }}</span></div>
                <div class="pb-progress" @touchstart.stop.prevent>
                  <div class="pp-track">
                    <div class="pp-played" :style="{ width: ((slotTimes[i].duration || 0) ? (slotTimes[i].current / slotTimes[i].duration) * 100 : 0) + '%' }"></div>
                  </div>
                  <div class="pp-time">{{ formatTime(slotTimes[i].current) }} / {{ formatTime(slotTimes[i].duration) }}</div>
                </div>
              </div>
            </template>
          </div>
        </div>
        <button class="portrait-exit" @click.stop="exitPortraitMode">退出</button>
        <div v-if="portraitSlots[PORTRAIT_CUR + 1] === null || portraitSlots[PORTRAIT_CUR - 1] === null" class="portrait-edge-hint">
          {{ curIndex === 0 ? '已经是第一个' : '已经是最后一个' }}
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
.portrait-bottom-bar {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 16px 14px 28px;
  background: linear-gradient(transparent, rgba(0, 0, 0, 0.7));
  transition: opacity 0.25s;
}
.portrait-bottom-bar.ui-hidden { opacity: 0; }
.pb-title { color: #fff; font-size: 14px; margin-bottom: 8px; }
.pp-track { position: relative; height: 4px; background: rgba(255, 255, 255, 0.3); border-radius: 2px; }
.pp-played { position: absolute; left: 0; top: 0; height: 100%; background: var(--accent); border-radius: 2px; }
.pp-time { color: #fff; font-size: 12px; margin-top: 6px; }
.portrait-exit {
  position: absolute;
  top: 16px;
  right: 16px;
  z-index: 10;
  background: rgba(0, 0, 0, 0.5);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 14px;
  font-size: 13px;
  cursor: pointer;
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
</style>
