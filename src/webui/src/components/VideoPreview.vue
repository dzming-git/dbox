<script setup lang="ts">
/**
 * VideoPreview - 视频预览组件（Sprite sheet + WebVTT）
 *
 * 取代旧 GIF 动图（256 色调色板 + 逐帧硬切导致闪烁）。进入视口后自动加载
 * 雪碧图 + VTT 索引，并以定时器按时间轴自动轮播帧（无 hover 依赖，桌面/移动端
 * 一致可看动图）；鼠标横向移动按 X 比例 seek 到对应时间点。离开视口自动停止
 * 播放以节省带宽。无雪碧图/VTT 时静默降级为静态海报。
 */
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { buildPreviewUrls, withThumbToken } from '../utils/media'

const props = defineProps<{
  hash?: string | null
  poster?: string | null   // 静态海报 URL（缺省时按 hash 推导 /thumbnail/{hash}）
  alt?: string
  autoplayIntervalMs?: number  // 自动轮播每帧间隔（默认 700ms）
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

// 播放/seek 状态
const inView = ref(false)     // 卡片是否在视口内
const isSeeking = ref(false)
const seekRatio = ref(0)      // 0~1，鼠标在卡片内的横向位置比例

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
let resumeTimer: number | null = null  // seek 结束后恢复自动播放的延迟
let currentFrame = 0
let disposed = false

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

// 是否正在显示动图（sprite 已加载且卡片在视口）
const showingSprite = computed(() => spriteLoaded.value && inView.value)

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
  if (!urls || spriteLoaded.value || spriteError.value || disposed) return

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
      if (inView.value && !disposed) startAutoplay()
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
  if (!spriteLoaded.value || autoplayTimer || !inView.value) return
  const n = cues.value.length
  if (!n) return
  currentFrame = 0
  const tick = () => {
    if (disposed || !inView.value || isSeeking.value) {
      autoplayTimer = null
      return
    }
    activeFrame.value = currentFrame % n
    currentFrame += 1
    autoplayTimer = window.setTimeout(tick, props.autoplayIntervalMs || 700)
  }
  tick()
}

function stopAutoplay() {
  if (autoplayTimer) {
    clearTimeout(autoplayTimer)
    autoplayTimer = null
  }
  if (resumeTimer) {
    clearTimeout(resumeTimer)
    resumeTimer = null
  }
}

function onMove(e: MouseEvent) {
  if (!inView.value || !spriteLoaded.value) return
  const box = root.value?.getBoundingClientRect()
  if (!box || !box.width) return
  const ratio = Math.min(1, Math.max(0, (e.clientX - box.left) / box.width))
  seekRatio.value = ratio
  isSeeking.value = true
  const idx = Math.min(cues.value.length - 1, Math.floor(ratio * cues.value.length))
  activeFrame.value = idx
  // 停止自动轮播，短暂延迟后恢复
  stopAutoplay()
  if (resumeTimer) clearTimeout(resumeTimer)
  resumeTimer = window.setTimeout(() => {
    isSeeking.value = false
    if (inView.value && !disposed) startAutoplay()
  }, 1500)
}

// IntersectionObserver：进入视口播放，离开视口停止
let observer: IntersectionObserver | null = null

watch(inView, (vis) => {
  if (vis) {
    loadPreview()
    startAutoplay()
  } else {
    stopAutoplay()
    isSeeking.value = false
    seekRatio.value = 0
    activeFrame.value = 0
  }
})

watch(() => props.hash, () => {
  // hash 变化：重置预览状态
  spriteLoaded.value = false
  spriteError.value = false
  spriteUrl.value = ''
  cues.value = []
  stopAutoplay()
  activeFrame.value = 0
  if (inView.value) loadPreview()
})

onMounted(() => {
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
  // 进入视口自动播放
  if (typeof IntersectionObserver !== 'undefined' && root.value) {
    observer = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          inView.value = en.isIntersecting
        }
      },
      { rootMargin: '80px 0px' }  // 提前 80px 预加载
    )
    observer.observe(root.value)
  } else {
    inView.value = true
  }
})

let resizeObserver: ResizeObserver | null = null
onBeforeUnmount(() => {
  disposed = true
  stopAutoplay()
  observer?.disconnect()
  observer = null
  resizeObserver?.disconnect()
  resizeObserver = null
})
</script>

<template>
  <div
    ref="root"
    class="video-preview"
    @mousemove="onMove"
    @mouseleave="isSeeking = false"
    @click="emit('click', $event)"
  >
    <!-- 静态海报（无 sprite 或未在视口时显示） -->
    <img
      class="preview-poster"
      :class="{ 'preview-active': showingSprite }"
      :src="posterSrc"
      :alt="alt"
      loading="lazy"
      draggable="false"
    />

    <!-- 自动轮播雪碧图帧层（进入视口后播放） -->
    <div
      v-show="showingSprite"
      class="preview-sprite"
      :style="{
        backgroundImage: `url(${spriteUrl})`,
        backgroundSize: bgSizeStyle,
        backgroundPosition: bgPosStyle,
        backgroundRepeat: 'no-repeat',
      }"
    ></div>

    <!-- 顶部进度条（seek 时联动） -->
    <div class="preview-progress" v-show="showingSprite">
      <div class="preview-progress-fill" :style="{ width: progressStyle }"></div>
    </div>

    <!-- 轻微亮度渐变遮罩 -->
    <div class="preview-vignette" v-show="showingSprite"></div>

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
  transition: opacity 0.25s ease, filter 0.25s ease;
}
/* 动图播放时海报淡出、透出雪碧图帧层，避免硬切闪烁 */
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
  pointer-events: none;
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
