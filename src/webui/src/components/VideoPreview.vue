<script setup lang="ts">
/**
 * VideoPreview - 视频悬停预览组件（Sprite sheet + WebVTT）
 *
 * 取代旧 GIF 动图（256 色调色板 + 逐帧硬切导致闪烁）。默认显示静态海报
 * （无闪烁、零额外带宽），鼠标悬停时懒加载雪碧图 + VTT 索引，按时间轴平滑
 * 轮播帧；鼠标横向移动按 X 比例 seek 到对应时间点。离开后复位为海报。
 * 无雪碧图/VTT 或移动端（无 hover）时静默降级为静态海报。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { buildPreviewUrls, withThumbToken } from '../utils/media'

const props = defineProps<{
  hash?: string | null
  poster?: string | null   // 静态海报 URL（缺省时按 hash 推导 /thumbnail/{hash}）
  alt?: string
  autoplayIntervalMs?: number  // 自动轮播每帧间隔（默认 600ms）
}>()

const emit = defineEmits<{
  (e: 'click', ev: MouseEvent): void
}>()

interface FrameCue {
  x: number
  y: number
  w: number
  h: number
  start: number
  end: number
}

const root = ref<HTMLElement | null>(null)
const posterEl = ref<HTMLImageElement | null>(null)

// 悬停/seek 状态
const isHovering = ref(false)
const isSeeking = ref(false)
const seekRatio = ref(0) // 0~1，鼠标在卡片内的横向位置比例

// sprite 数据
const spriteUrl = ref('')
const spriteLoaded = ref(false)
const spriteError = ref(false)
const cues = ref<FrameCue[]>([])
const spriteW = ref(0)
const spriteH = ref(0)
const frameW = ref(0)
const frameH = ref(0)
const containerW = ref(0)
const containerH = ref(0)

// 自动轮播游标
let autoplayTimer: number | null = null
let currentFrame = 0
let disposed = false

// 移动端 / 无 hover：不做懒加载
const isFinePointer = typeof window !== 'undefined'
  ? window.matchMedia('(hover: hover) and (pointer: fine)').matches
  : true

// 海报地址：优先显式 poster，否则按 hash 推导
const posterSrc = computed(() => {
  if (props.poster) return withThumbToken(props.poster)
  if (props.hash) return withThumbToken(`/thumbnail/${props.hash}`)
  return '/placeholder.jpg'
})

// 当前显示的帧（用于 background-position 计算）
const activeFrame = ref(0)

// 背景尺寸：整张雪碧图缩放到「单帧覆盖卡片盒」的比例
const bgSizeStyle = computed(() => {
  if (!spriteW.value || !frameW.value || !frameH.value) return ''
  const scale = Math.max(
    containerW.value / frameW.value,
    containerH.value / frameH.value
  )
  const sw = spriteW.value * scale
  const sh = spriteH.value * scale
  return `${sw}px ${sh}px`
})

// 背景定位：把目标帧的左上角对齐到容器左上角
const bgPosStyle = computed(() => {
  const frame = cues.value[activeFrame.value]
  if (!frame || !frameW.value) return '0px 0px'
  const scale = Math.max(
    containerW.value / frameW.value,
    containerH.value / frameH.value
  )
  return `-${frame.x * scale}px -${frame.y * scale}px`
})

// 顶部进度条宽度（随 seek 位置联动）
const progressStyle = computed(() => `${(isSeeking.value ? seekRatio.value : 0) * 100}%`)

function parseVtt(text: string): { cues: FrameCue[]; fw: number; fh: number } {
  const lines = text.split(/\r?\n/)
  const cuesOut: FrameCue[] = []
  let fw = 0
  let fh = 0

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim()
    // NOTE 行携带几何：sprite fw=180 fh=136 cols=4 rows=3 n=12 ...
    if (line.startsWith('NOTE')) {
      const fwm = line.match(/\bfw=(\d+)/)
      const fhm = line.match(/\bfh=(\d+)/)
      if (fwm) fw = parseInt(fwm[1], 10)
      if (fhm) fh = parseInt(fhm[1], 10)
      continue
    }
    // cue 时间行：00:00:00.800 --> 00:00:01.500
    const tm = line.match(/^(\d+):(\d+):([\d.]+)\s*-->\s*(\d+):(\d+):([\d.]+)/)
    if (tm) {
      const start = toSeconds(tm[1], tm[2], tm[3])
      const end = toSeconds(tm[4], tm[5], tm[6])
      // 下一行应是 xywh=x,y,w,h
      const xy = lines[i + 1]?.trim().match(/^xywh=(\d+),(\d+),(\d+),(\d+)/)
      if (xy) {
        cuesOut.push({
          x: parseInt(xy[1], 10),
          y: parseInt(xy[2], 10),
          w: parseInt(xy[3], 10),
          h: parseInt(xy[4], 10),
          start,
          end,
        })
        i += 1
      }
    }
  }
  return { cues: cuesOut, fw, fh }
}

function toSeconds(h: string, m: string, s: string): number {
  return parseInt(h, 10) * 3600 + parseInt(m, 10) * 60 + parseFloat(s)
}

async function loadPreview() {
  const urls = buildPreviewUrls(props.hash)
  if (!urls || spriteLoaded.value || spriteError.value) return

  try {
    // 先取 VTT（轻量），成功后再加载雪碧图
    const vttRes = await fetch(urls.vttUrl)
    if (!vttRes.ok) throw new Error('vtt not found')
    const vttText = await vttRes.text()
    const parsed = parseVtt(vttText)
    if (!parsed.cues.length) throw new Error('empty cues')
    cues.value = parsed.cues
    frameW.value = parsed.fw || parsed.cues[0].w
    frameH.value = parsed.fh || parsed.cues[0].h

    // 预加载雪碧图
    const img = new Image()
    img.onload = () => {
      spriteW.value = img.naturalWidth
      spriteH.value = img.naturalHeight
      spriteLoaded.value = true
      spriteUrl.value = urls.spriteUrl
      if (isHovering.value && !disposed) startAutoplay()
    }
    img.onerror = () => {
      spriteError.value = true
    }
    img.src = urls.spriteUrl
  } catch (e) {
    console.error('[VideoPreview] 预览加载失败', e)
    spriteError.value = true
  }
}

function startAutoplay() {
  if (!spriteLoaded.value || autoplayTimer) return
  const n = cues.value.length
  if (!n) return
  currentFrame = 0
  const tick = () => {
    if (disposed || !isHovering.value || isSeeking.value) {
      autoplayTimer = null
      return
    }
    activeFrame.value = currentFrame % n
    currentFrame += 1
    autoplayTimer = window.setTimeout(tick, props.autoplayIntervalMs || 600)
  }
  tick()
}

function stopAutoplay() {
  if (autoplayTimer) {
    clearTimeout(autoplayTimer)
    autoplayTimer = null
  }
}

function onEnter(e: MouseEvent) {
  if (!isFinePointer || spriteError.value) return
  isHovering.value = true
  const box = root.value?.getBoundingClientRect()
  if (box) {
    containerW.value = box.width
    containerH.value = box.height
  }
  loadPreview()
}

function onMove(e: MouseEvent) {
  if (!isHovering.value || !spriteLoaded.value) return
  const box = root.value?.getBoundingClientRect()
  if (!box || !box.width) return
  const ratio = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width))
  seekRatio.value = ratio
  isSeeking.value = true
  const idx = Math.min(cues.value.length - 1, Math.floor(ratio * cues.value.length))
  activeFrame.value = idx
}

function onLeave() {
  isHovering.value = false
  isSeeking.value = false
  seekRatio.value = 0
  stopAutoplay()
  // 复位海报
  spriteLoaded.value = false
  activeFrame.value = 0
  // 保留 cues/sprite 缓存以快速复现，但海报层重新显现
}

watch(() => props.hash, () => {
  // hash 变化：重置预览状态
  spriteLoaded.value = false
  spriteError.value = false
  spriteUrl.value = ''
  cues.value = []
  stopAutoplay()
  activeFrame.value = 0
})

onMounted(() => {
  // 监听尺寸变化，保证 background 缩放正确
  const box = root.value?.getBoundingClientRect()
  if (box) {
    containerW.value = box.width
    containerH.value = box.height
  }
  if (typeof ResizeObserver !== 'undefined' && root.value) {
    resizeObserver = new ResizeObserver(() => {
      const b = root.value?.getBoundingClientRect()
      if (b) {
        containerW.value = b.width
        containerH.value = b.height
      }
    })
    resizeObserver.observe(root.value)
  }
})

let resizeObserver: ResizeObserver | null = null
onBeforeUnmount(() => {
  disposed = true
  stopAutoplay()
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div
    ref="root"
    class="video-preview"
    @mouseenter="onEnter"
    @mousemove="onMove"
    @mouseleave="onLeave"
    @click="emit('click', $event)"
  >
    <!-- 默认静态海报（无 sprite 或未 hover 时显示） -->
    <img
      ref="posterEl"
      class="preview-poster"
      :class="{ 'preview-active': spriteLoaded && isHovering }"
      :src="posterSrc"
      :alt="alt"
      loading="lazy"
      draggable="false"
    />

    <!-- hover 态雪碧图帧层 -->
    <div
      v-show="spriteLoaded && isHovering"
      class="preview-sprite"
      :style="{
        backgroundImage: `url(${spriteUrl})`,
        backgroundSize: bgSizeStyle,
        backgroundPosition: bgPosStyle,
        backgroundRepeat: 'no-repeat',
      }"
    ></div>

    <!-- 顶部进度条（随 seek 位置联动） -->
    <div class="preview-progress" v-show="spriteLoaded && isHovering">
      <div class="preview-progress-fill" :style="{ width: progressStyle }"></div>
    </div>

    <!-- 悬停轻微亮度渐变遮罩 -->
    <div class="preview-vignette" v-show="isHovering"></div>

    <slot></slot>
  </div>
</template>

<style scoped>
.video-preview {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--bg-surface);
  cursor: pointer;
}
.preview-poster {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  transition: opacity 0.2s ease, filter 0.2s ease;
}
/* hover 时海报淡出、透出雪碧图帧层，避免硬切闪烁 */
.preview-poster.preview-active {
  opacity: 0;
  filter: brightness(0.98);
}
.preview-sprite {
  position: absolute;
  inset: 0;
  background-color: #000;
}
.preview-progress {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 3px;
  background: rgba(0, 0, 0, 0.35);
  z-index: 3;
}
.preview-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--accent), var(--accent-hover, var(--accent)));
  transition: width 0.05s linear;
}
.preview-vignette {
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: linear-gradient(180deg, rgba(0, 0, 0, 0.06), rgba(0, 0, 0, 0.12));
  z-index: 2;
}
</style>
