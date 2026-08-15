<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, reactive, onActivated, onDeactivated, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import { useUserStore } from '../stores/userStore'
import { tagApi, videoApi, collectionSetApi, resourceApi, historyApi } from '../api'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import { getEffectiveSettings } from '../utils/settings'
import ItemEditDrawer from '../components/ItemEditDrawer.vue'
import CollectionPanel from '../components/CollectionPanel.vue'
import type { Video, Tag, VideoTagRef, VideoMarker } from '../types'
import { withThumbToken } from '../utils/media'

const route = useRoute()
const router = useRouter()
const videoStore = useVideoStore()
const userStore = useUserStore()

// 检查当前用户是否为管理员（使用 userStore 的统一判断）
const isAdmin = computed(() => userStore.isAdmin)

// 资源所属权：管理员或上传本人可编辑/删除
const canManageVideo = computed(() => {
  if (isAdmin.value) return true
  const uid = userStore.user?.id
  return !!uid && video.value?.owner_id === uid
})

// 视频编辑抽屉（管理员可编辑标题/简介/资源库/标签）
const editDrawerVisible = ref(false)
const editingItem = ref<any>(null)

const video = ref<Video | null>(null)
const loading = ref(true)
const isFavorited = ref(false)
const isLiked = ref(false)
const isDisliked = ref(false)
const videoPlayer = ref<HTMLVideoElement | null>(null)
const isPlaying = ref(false)
const isFullscreen = ref(false)

// 移动端手势控制
const isMobile = ref(false)
const isTouchMode = computed(() => isMobile.value && !isFullscreen.value)
const touchStartX = ref(0)
const touchStartY = ref(0)
const touchStartCurrent = ref(0)
const touchMoved = ref(false)
const lastTapTime = ref(0)
const tapTimer = ref<number | null>(null)
const seekFeedbackVisible = ref(false)
const seekFeedbackText = ref('')
let seekFeedbackTimer: number | null = null

const updateMobileState = () => {
  // 触摸设备（pointer: coarse）或窄视口（手机竖屏/小窗模式）均启用自定义控制栏
  const coarse = window.matchMedia('(pointer: coarse)').matches
  const narrow = window.innerWidth <= 768
  isMobile.value = coarse || narrow
}
const updateFullscreenState = () => {
  isFullscreen.value = !!document.fullscreenElement
}
const togglePlay = () => {
  const p = videoPlayer.value
  if (!p) return
  if (p.paused) p.play().catch(() => {})
  else p.pause()
}

// 全屏切换
const toggleFullscreen = () => {
  const el = videoPlayer.value?.parentElement || videoPlayer.value
  if (!el) return
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {})
  } else {
    el.requestFullscreen?.().catch(() => {})
  }
}

// ===== 竖屏全屏短视频模式（抖音式沉浸播放 · 跟手 feed track）=====
// playMode: 'normal' 详情模式 / 'portrait' 竖屏沉浸模式
const playMode = ref<'normal' | 'portrait'>('normal')
const portraitPlayer = ref<HTMLVideoElement | null>(null)
const feedList = ref<string[]>([]) // 累积的视频 hash 序列（记住历史）
const feedIndex = ref(0) // 当前播放位置
const portraitLoading = ref(false)
const portraitHash = computed(() => feedList.value[feedIndex.value] || videoHash.value)
const showPortraitDoubleLike = ref(false) // 双击爱心动画
let doubleLikeTimer: number | null = null

// 跟手滑动轨道状态
const portraitDragY = ref(0) // 当前轨道纵向位移（px，跟手指）
const portraitDragging = ref(false) // 是否正在拖动（关闭 transition）
const portraitTransition = ref(false) // 是否开启吸附动画
const portraitViewportH = ref(0) // 视口高度（用于阈值与位移比例）
// 相邻视频预览缓存：{ hash, title, cover, file_name }
const portraitPrevPreview = ref<any>(null)
const portraitNextPreview = ref<any>(null)
const portraitSwitching = ref(false) // 吸附动画进行中，防重复触发

// 轨道实时 translateY：current 始终位于第 2 格（index=1），基准 -viewportH
const portraitTrackY = computed(() => {
  const base = -portraitViewportH.value // current 在第 2 格
  return base + portraitDragY.value
})

// 从路由 query 初始化播放模式
const initPlayMode = () => {
  playMode.value = route.query.mode === 'portrait' ? 'portrait' : 'normal'
}

// 进入竖屏模式：把当前视频作为流首，自动播放
const enterPortraitMode = () => {
  feedList.value = [videoHash.value]
  feedIndex.value = 0
  portraitVideo.value = video.value
  portraitDragY.value = 0
  portraitPrevPreview.value = null
  portraitNextPreview.value = null
  syncPortraitInteractions()
  playMode.value = 'portrait'
  portraitViewportH.value = window.innerHeight
  // 标记竖屏激活，阻止底层 PullToRefresh 接管手势
  document.body.classList.add('portrait-mode-active')
  router.replace({ name: 'Video', params: { hash: videoHash.value }, query: { ...route.query, mode: 'portrait' } })
  nextTick(() => {
    portraitPlayer.value?.play().catch(() => {})
  })
}

// 同步竖屏当前视频的互动状态到本地 ref
const syncPortraitInteractions = () => {
  const v = portraitVideo.value
  if (!v) return
  isLiked.value = !!v.is_liked
  isFavorited.value = !!v.is_favorited
  isDisliked.value = !!v.is_disliked
}

// 退出竖屏模式，回到普通详情页
const exitPortraitMode = () => {
  playMode.value = 'normal'
  // 移除竖屏标记，恢复底层下拉刷新
  document.body.classList.remove('portrait-mode-active')
  const q = { ...route.query }
  delete q.mode
  router.replace({ name: 'Video', params: { hash: portraitHash.value }, query: q })
  // 同步详情页视频源
  if (videoHash.value !== portraitHash.value) {
    router.replace({ name: 'Video', params: { hash: portraitHash.value }, query: q })
  }
}

// 竖屏模式下跳转详情页（普通模式）
const openDetailFromPortrait = () => {
  const q = { ...route.query }
  delete q.mode
  router.push({ name: 'Video', params: { hash: portraitHash.value }, query: q })
}

// 竖屏模式下请求横屏全屏（原生全屏）
const enterLandscapeFromPortrait = () => {
  playMode.value = 'normal'
  const q = { ...route.query }
  delete q.mode
  router.replace({ name: 'Video', params: { hash: portraitHash.value }, query: q })
  nextTick(() => {
    toggleFullscreen()
  })
}

// 竖屏视频数据对象
const portraitVideo = ref<any>(null)

// 加载指定 hash 的视频到竖屏播放器
const loadPortraitVideo = async (hash: string) => {
  portraitLoading.value = true
  try {
    const res = await (videoApi.getVideo(hash) as any)
    if (res?.success && res.video) {
      portraitVideo.value = res.video
    } else if (res?.video) {
      portraitVideo.value = res.video
    }
    syncPortraitInteractions()
  } catch (e) {
    console.error('竖屏加载视频失败:', e)
  } finally {
    portraitLoading.value = false
    nextTick(() => {
      portraitPlayer.value?.play().catch(() => {})
    })
  }
}

// 预取下一个随机视频预览（下滑方向）：从推荐接口取一个非当前视频
const fetchNextPreview = async () => {
  if (portraitNextPreview.value) return
  try {
    const response = await (videoApi.getVideos({ limit: 10, sort: 'recommended' }) as any)
    const list: any[] = response?.videos || []
    const next = list.find((v) => v.hash !== portraitHash.value)
    if (next) {
      portraitNextPreview.value = {
        hash: next.hash,
        title: next.title,
        file_name: next.file_name,
        cover: next.cover || next.thumbnail,
      }
    }
  } catch (e) {
    console.error('预取下一个视频失败:', e)
  }
}

// 上一个视频（下滑）：回退到历史位置（记住，不重新请求）
const loadPrevPortraitVideo = () => {
  if (feedIndex.value > 0) {
    feedIndex.value -= 1
    const h = feedList.value[feedIndex.value]
    loadPortraitVideo(h)
    return true
  }
  return false
}

// 下一个随机视频（上滑）：从预览缓存取 hash，追加到 feedList 并加载
const loadNextPortraitVideo = async () => {
  if (!portraitNextPreview.value) {
    await fetchNextPreview()
  }
  if (portraitNextPreview.value) {
    const h = portraitNextPreview.value.hash
    feedList.value.push(h)
    feedIndex.value = feedList.value.length - 1
    portraitPrevPreview.value = {
      hash: portraitHash.value,
      title: portraitVideo.value?.title,
      file_name: portraitVideo.value?.file_name,
      cover: portraitVideo.value?.cover || portraitVideo.value?.thumbnail,
    }
    portraitNextPreview.value = null
    await loadPortraitVideo(h)
    fetchNextPreview() // 继续预取下一个
    return true
  }
  showToast('没有更多视频了')
  return false
}

// ===== 跟手滑动手势 =====
const portraitTouchStartY = ref(0)
const portraitTouchStartX = ref(0)
const onPortraitTouchStart = (e: TouchEvent) => {
  const t = e.touches[0]
  if (!t) return
  portraitTouchStartY.value = t.clientY
  portraitTouchStartX.value = t.clientX
  portraitDragging.value = true
  portraitTransition.value = false
  portraitViewportH.value = window.innerHeight
}
const onPortraitTouchMove = (e: TouchEvent) => {
  if (!portraitDragging.value || portraitSwitching.value) return
  const t = e.touches[0]
  if (!t) return
  const dy = t.clientY - portraitTouchStartY.value
  const dx = t.clientX - portraitTouchStartX.value
  // 限制横向滑动不跟手（保留给可能的横向操作）
  if (Math.abs(dy) < Math.abs(dx)) {
    portraitDragY.value = 0
    return
  }
  portraitDragY.value = dy
}
const PORTRAIT_SWIPE_THRESHOLD = 60
const onPortraitTouchEnd = (e: TouchEvent) => {
  if (!portraitDragging.value) return
  portraitDragging.value = false
  const t = e.changedTouches[0]
  if (!t) return
  const dy = t.clientY - portraitTouchStartY.value
  const dx = t.clientX - portraitTouchStartX.value
  portraitTransition.value = true // 开启吸附动画
  if (Math.abs(dy) < PORTRAIT_SWIPE_THRESHOLD || Math.abs(dy) <= Math.abs(dx)) {
    // 未达阈值：回弹
    portraitDragY.value = 0
    return
  }
  if (dy < 0) {
    // 上滑：切到下一个（随机），轨道向上飞
    portraitSwitching.value = true
    portraitDragY.value = -portraitViewportH.value
    setTimeout(async () => {
      const ok = await loadNextPortraitVideo()
      // 切换后瞬时归位到 current（无动画）
      portraitTransition.value = false
      portraitDragY.value = 0
      portraitSwitching.value = false
      if (!ok) portraitDragY.value = 0
    }, 280)
  } else {
    // 下滑：回到上一个（历史），轨道向下飞
    const ok = loadPrevPortraitVideo()
    if (ok) {
      portraitSwitching.value = true
      portraitDragY.value = portraitViewportH.value
      setTimeout(() => {
        portraitTransition.value = false
        portraitDragY.value = 0
        portraitSwitching.value = false
      }, 280)
    } else {
      portraitDragY.value = 0
    }
  }
}

// 竖屏双击点赞
const portraitLastTap = ref(0)
const onPortraitTap = () => {
  const now = Date.now()
  if (now - portraitLastTap.value < 300) {
    portraitLastTap.value = 0
    if (!isLiked.value) handleLike()
    showPortraitDoubleLike.value = true
    if (doubleLikeTimer) clearTimeout(doubleLikeTimer)
    doubleLikeTimer = window.setTimeout(() => { showPortraitDoubleLike.value = false }, 700)
  } else {
    portraitLastTap.value = now
  }
}

// 竖屏内点赞/收藏/不喜欢：直接基于竖屏当前视频 hash 调后端，同步本地状态
const portraitHandleLike = async () => {
  const h = portraitHash.value
  if (!h) return
  const response = await (videoStore.likeVideo(h) as any)
  if (response && response.like_count !== undefined) {
    isLiked.value = response.liked
    if (portraitVideo.value) portraitVideo.value.like_count = response.like_count
  }
}
const portraitHandleFavorite = async () => {
  const h = portraitHash.value
  if (!h) return
  const response = await (videoStore.favoriteVideo(h) as any)
  if (response && response.favorite_count !== undefined) {
    isFavorited.value = response.favorited
    if (portraitVideo.value) portraitVideo.value.favorite_count = response.favorite_count
  }
  showToast(isFavorited.value ? '已添加到收藏' : '已取消收藏')
}
const portraitHandleDislike = async () => {
  const h = portraitHash.value
  if (!h) return
  if (isLiked.value) {
    const r = await (videoStore.likeVideo(h) as any)
    isLiked.value = r?.liked ?? false
  }
  const response = await (videoStore.dislikeVideo(h) as any)
  if (response && response.success) {
    isDisliked.value = response.disliked
  } else {
    isDisliked.value = !isDisliked.value
  }
  showToast(isDisliked.value ? '已屏蔽，将不再出现在列表中' : '已取消屏蔽')
}

// 竖屏视频源 URL：优先 portraitVideo.url，fallback 到详情页 video.url（同一视频时复用）
const portraitVideoUrl = computed(() => {
  // 优先使用竖屏视频自己的 url
  const url = portraitVideo.value?.url || (portraitHash.value === videoHash.value ? video.value?.url : '') || ''
  if (url) {
    const token = localStorage.getItem('token')
    // 相对路径转绝对路径，避免 iOS 上父级代理路径解析错误
    const abs = url.startsWith('http') ? url : `${location.origin}${url.startsWith('/') ? '' : '/'}${url}`
    return token ? `${abs}${abs.includes('?') ? '&' : '?'}${token ? `token=${token}` : ''}` : abs
  }
  // fallback: 若竖屏视频就是当前详情页视频，复用 videoUrl
  if (portraitHash.value === videoHash.value) {
    return videoUrl.value
  }
  return ''
})

// 竖屏视频播放结束：自动进入下一个（带轨道吸附动画）
const onPortraitEnded = () => {
  if (portraitSwitching.value) return
  portraitTransition.value = true
  portraitSwitching.value = true
  portraitDragY.value = -portraitViewportH.value
  setTimeout(async () => {
    const ok = await loadNextPortraitVideo()
    portraitTransition.value = false
    portraitDragY.value = 0
    portraitSwitching.value = false
    if (!ok) portraitDragY.value = 0
  }, 280)
}

// 移动端控制栏自动隐藏
const showControls = ref(true)
let controlsTimer: number | null = null
const showControlsTemporarily = () => {
  showControls.value = true
  if (controlsTimer) window.clearTimeout(controlsTimer)
  controlsTimer = window.setTimeout(() => {
    // 仅在点暂停或静止时自动隐藏，播放中且未交互才隐藏
    if (isPlaying.value && !isBuffering.value) showControls.value = false
  }, 3000)
}

// 缓冲/网速状态
const isBuffering = ref(false)
const netSpeed = ref(0) // KB/s
let speedTimer: number | null = null
let speedBytesStart = 0
let speedTimeStart = 0

const onWaiting = () => {
  isBuffering.value = true
  showControls.value = true
  if (controlsTimer) window.clearTimeout(controlsTimer)
  startSpeedMonitor()
}

const onPlaying = () => {
  // 播放恢复，结束缓冲转圈
  isBuffering.value = false
  startSpeedMonitor()
}

const onStalled = () => {
  isBuffering.value = true
  showControls.value = true
  if (controlsTimer) window.clearTimeout(controlsTimer)
}

// 通过轮询 video.buffered 末端字节估算网速
const startSpeedMonitor = () => {
  if (speedTimer) window.clearInterval(speedTimer)
  speedBytesStart = videoPlayer.value?.buffered.length
    ? videoPlayer.value.buffered.end(videoPlayer.value.buffered.length - 1) * (videoPlayer.value.videoWidth * videoPlayer.value.videoHeight * 0.08)
    : 0
  speedTimeStart = performance.now()
  speedTimer = window.setInterval(() => {
    const v = videoPlayer.value
    if (!v || !v.buffered.length) return
    const bufferedEnd = v.buffered.end(v.buffered.length - 1)
    const bytes = bufferedEnd * (v.videoWidth * v.videoHeight * 0.08)
    const dt = (performance.now() - speedTimeStart) / 1000
    if (dt > 0) {
      const kbps = (bytes - speedBytesStart) / 1024 / dt
      netSpeed.value = kbps > 0 ? kbps : 0
    }
    speedBytesStart = bytes
    speedTimeStart = performance.now()
  }, 1000)
}

// 精彩片段标记（用户个人时间戳）
const markers = ref<VideoMarker[]>([])
const showMarkerForm = ref(false)
const markerNote = ref('')
const currentTime = ref(0)
// 优先用 <video> 元素自身的 duration（元信息加载后最准确），回退到后端返回的 video.duration
const videoDuration = computed(() => {
  void durationLoaded.value
  const el = videoPlayer.value
  if (el && isFinite(el.duration) && el.duration > 0) return el.duration
  return Number(video.value?.duration) || 0
})
const markerTrack = computed(() => {
  if (!videoDuration.value) return []
  return markers.value
    .filter((m) => m.time_seconds >= 0 && m.time_seconds <= videoDuration.value)
    .map((m) => ({
      id: m.id,
      time: m.time_seconds,
      note: m.note || '精彩片段',
      left: (m.time_seconds / videoDuration.value) * 100,
    }))
})
const seekTo = (time: number) => {
  const player = videoPlayer.value
  if (player) {
    player.currentTime = time
    player.play().catch(() => {})
  }
}

const formatTime = (sec: number) => {
  const s = Math.max(0, Math.floor(sec || 0))
  const m = Math.floor(s / 60)
  const r = s % 60
  const h = Math.floor(m / 60)
  const mm = h > 0 ? String(m % 60).padStart(2, '0') : String(m)
  const ss = String(r).padStart(2, '0')
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

const formatSpeed = (kbps: number) => {
  if (kbps >= 1024) return (kbps / 1024).toFixed(1) + ' MB'
  return Math.round(kbps) + ' KB'
}

// 移动端进度条拖动/点击跳转
const progressBarRef = ref<HTMLElement | null>(null)
const draggingProgress = ref(false)
const seekFromBar = (e: MouseEvent | TouchEvent) => {
  const bar = progressBarRef.value
  const player = videoPlayer.value
  if (!bar || !player) return
  const rect = bar.getBoundingClientRect()
  const clientX = 'touches' in e ? (e as TouchEvent).touches[0]?.clientX : (e as MouseEvent).clientX
  if (clientX == null) return
  const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  player.currentTime = ratio * (Number(player.duration) || videoDuration.value)
  if (isPlaying.value) player.play().catch(() => {})
}

const videoHash = computed(() => route.params.hash as string)

// —— 合集连播上下文 ——
const collectionId = ref<number | null>(null)
const collectionItems = ref<{ type: string; hash: string; title?: string }[]>([])
const collectionName = ref('')
// 视频所属合集（分类归属展示，与合集连播上下文无关）
const videoCollections = ref<{ id: number; name: string }[]>([])
// 是否已在「继续观看」列表（用户主动加入，不自动按打开行为加入）
const inContinueWatch = ref(false)
const inCollection = computed(() => collectionId.value !== null && collectionItems.value.length > 0)
const currentIndex = computed(() =>
  collectionItems.value.findIndex(i => i.type === 'video' && i.hash === videoHash.value)
)
const prevItem = computed(() =>
  currentIndex.value > 0 ? collectionItems.value[currentIndex.value - 1] : null
)
const nextItem = computed(() =>
  currentIndex.value >= 0 && currentIndex.value < collectionItems.value.length - 1
    ? collectionItems.value[currentIndex.value + 1] : null
)
const loadCollectionContext = async () => {
  const c = route.query.collection
  collectionId.value = c ? Number(c) : null
  collectionItems.value = []
  collectionName.value = ''
  if (!collectionId.value) return
  try {
    const itemsRes = await (collectionSetApi.getItems(collectionId.value) as any)
    if (itemsRes?.success) {
      collectionItems.value = (itemsRes.items || []).map((it: any) => ({
        type: it.media?.type || it.item_type,
        hash: it.media?.hash || it.item_hash,
        title: it.media?.title,
      }))
    }
    const colRes = await (collectionSetApi.getCollection(collectionId.value) as any)
    if (colRes?.success) collectionName.value = colRes.collection.name
  } catch (e) {
    console.error(e)
  }
}
const goCollectionItem = (it: { type: string; hash: string }) => {
  const base = it.type === 'video' ? '/video/' : '/gallery/'
  router.push(`${base}${it.hash}?collection=${collectionId.value}`)
}
// 查询视频所属的全部合集（用于信息区“分类归属”展示）
const loadVideoCollections = () => {
  const h = (video.value && video.value.hash) || videoHash.value
  if (!h) return
  collectionSetApi.getByItem('video', h)
    .then((res: any) => {
      if (res?.success && Array.isArray(res.collections)) {
        videoCollections.value = res.collections.map((c: any) => ({ id: c.id, name: c.name }))
      }
    })
    .catch(() => {})
}

// 「继续观看」列表（显式加入，存于本地，避免打开即占用首页面板）
const CONTINUE_WATCH_KEY = 'continueWatch'
const loadContinueWatchState = () => {
  if (!video.value) return
  try {
    const arr = JSON.parse(localStorage.getItem(CONTINUE_WATCH_KEY) || '[]')
    inContinueWatch.value = Array.isArray(arr) && arr.some((x: any) => x.hash === video.value!.hash)
  } catch {
    inContinueWatch.value = false
  }
}
const toggleContinueWatch = () => {
  if (!video.value) return
  let arr: any[] = []
  try {
    arr = JSON.parse(localStorage.getItem(CONTINUE_WATCH_KEY) || '[]')
    if (!Array.isArray(arr)) arr = []
  } catch {
    arr = []
  }
  const idx = arr.findIndex((x: any) => x.hash === video.value!.hash)
  if (idx >= 0) {
    arr.splice(idx, 1)
    inContinueWatch.value = false
  } else {
    arr.push({
      hash: video.value.hash,
      title: video.value.title,
      thumbnail: video.value.thumbnail || video.value.cover_url || '',
      cover_url: video.value.cover_url || video.value.thumbnail || '',
      duration: video.value.duration || 0,
      updated_at: Date.now(),
    })
    inContinueWatch.value = true
  }
  localStorage.setItem(CONTINUE_WATCH_KEY, JSON.stringify(arr))
}
// 自动续播：播放结束后 3 秒倒计时跳转
const autoContinueVisible = ref(false)
const autoContinueCountdown = ref(3)
const autoContinueTarget = ref<{ type: string; hash: string; title?: string } | null>(null)
let autoContinueTimer: number | null = null

const pickAutoContinueTarget = (): { type: string; hash: string; title?: string } | null => {
  if (nextItem.value) return nextItem.value
  const rec = recommendedVideos.value.find((v) => v.hash !== videoHash.value)
  if (rec) return { type: 'video', hash: rec.hash, title: rec.title }
  return null
}

const clearAutoContinueTimer = () => {
  if (autoContinueTimer !== null) {
    clearInterval(autoContinueTimer)
    autoContinueTimer = null
  }
  autoContinueVisible.value = false
}

const startAutoContinue = () => {
  const target = pickAutoContinueTarget()
  if (!target) return
  autoContinueTarget.value = target
  autoContinueCountdown.value = 3
  autoContinueVisible.value = true
  autoContinueTimer = window.setInterval(() => {
    autoContinueCountdown.value -= 1
    if (autoContinueCountdown.value <= 0) {
      clearAutoContinueTimer()
      goCollectionItem(target)
    }
  }, 1000)
}

const cancelAutoContinue = () => {
  clearAutoContinueTimer()
}

const stopSpeedMonitor = () => {
  if (speedTimer) {
    window.clearInterval(speedTimer)
    speedTimer = null
  }
}

const onVideoEnded = () => {
  isBuffering.value = false
  netSpeed.value = 0
  stopSpeedMonitor()
  if (!getEffectiveSettings().autoContinue) {
    if (nextItem.value) goCollectionItem(nextItem.value)
    return
  }
  if (!pickAutoContinueTarget()) {
    if (nextItem.value) goCollectionItem(nextItem.value)
    return
  }
  startAutoContinue()
}

// 推荐视频相关状态
const recommendedVideos = ref<Video[]>([])
const recommendedLoading = ref(false)

// 共享观看相关状态
const shareCode = ref<string>('')
const sharedSession = ref<any>(null)
const isSharedMode = ref(false)
const isCreator = ref(false)
const showShareDialog = ref(false)
const showMoreMenu = ref(false)
const shareUrl = ref('')
const syncInterval = ref<number | null>(null)
const lastSyncTime = ref(0)

// 视频源URL - 使用后端返回的 url 字段（/api/videos/{id}/play），拼接 token 用于认证
const videoUrl = computed(() => {
  const url = video.value?.url || ''
  if (!url) return ''
  const token = localStorage.getItem('token')
  return token ? `${url}?token=${token}` : url
})

// 完整加载一个视频（含标记/历史/合集上下文）。供 onMounted 与切换视频复用。
const loadVideo = async () => {
  if (!videoHash.value) return
  loading.value = true
  try {
    const response = await videoStore.fetchVideo(videoHash.value)
    if (response && response.video) {
      video.value = response.video
      await loadMarkers()
      await incrementViewCount()
      await addToHistory()
      loadUserInteractions()
      fetchRecommendedVideos()
      await loadCollectionContext()
      loadVideoCollections()
      loadContinueWatchState()

      // 若当前是竖屏模式，同步 portraitVideo（确保视频源可用）
      if (playMode.value === 'portrait' && video.value) {
        if (!portraitVideo.value || portraitVideo.value.hash !== video.value.hash) {
          portraitVideo.value = video.value
          syncPortraitInteractions()
        }
      }
    }
  } catch (error) {
    console.error('Failed to load video:', error)
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  // 先检查是否是共享链接访问
  await checkSharedLink()
  await loadVideo()
  initPlayMode()
  document.addEventListener('click', onDocClickCloseMenu)
  updateMobileState()
  updateFullscreenState()
  window.addEventListener('resize', updateMobileState)
  document.addEventListener('fullscreenchange', updateFullscreenState)
})

// 路由 query.mode 变化时同步竖屏模式（支持外链直接进入竖屏）
watch(() => route.query.mode, (m) => {
  const target = m === 'portrait' ? 'portrait' : 'normal'
  if (target === 'portrait' && playMode.value !== 'portrait') {
    feedList.value = [videoHash.value]
    feedIndex.value = 0
    portraitVideo.value = video.value
    syncPortraitInteractions()
  }
  playMode.value = target
})

// 顶部下拉刷新：重新加载当前视频及其推荐
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(loadVideo)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())

function onDocClickCloseMenu(e: Event) {
  if (!moreMenuOpen.value) return
  const wrap = document.querySelector('.more-menu-wrap')
  if (wrap && !wrap.contains(e.target as Node)) moreMenuOpen.value = false
}

// 切换视频（含合集内上一集/下一集）时重新加载
watch(videoHash, async () => {
  clearAutoContinueTimer()
  await loadVideo()
})

// 从后端加载用户交互状态（登录用户绑定账号，跨设备一致，以后端为准）
const loadUserInteractions = () => {
  if (!video.value) return
  isFavorited.value = !!video.value.is_favorited
  isLiked.value = !!video.value.is_liked
  isDisliked.value = !!video.value.is_disliked
}

// 获取推荐视频
const fetchRecommendedVideos = async () => {
  recommendedLoading.value = true
  try {
    const params: any = { limit: 8, sort: 'recommended' }
    const response = await videoApi.getVideos(params) as any
    // 过滤掉当前视频
    recommendedVideos.value = response.videos.filter((v: Video) => v.hash !== videoHash.value)
  } catch (e) {
    console.error('获取推荐视频失败:', e)
  } finally {
    recommendedLoading.value = false
  }
}

// 点击推荐视频
const handleRecommendationClick = (targetVideo: Video) => {
  // 携带当前视频的 from 参数，以便返回时恢复状态
  const currentQuery = route.query
  const fromQuery: Record<string, string> = {}
  if (Object.keys(currentQuery).length > 0 && currentQuery.from) {
    fromQuery.from = currentQuery.from as string
  }
  router.push({ name: 'Video', params: { hash: targetVideo.hash }, query: fromQuery })
}

// 上报观看进度到后端（后端为唯一数据源，登录账号跨设备一致）
const reportHistory = async (progress: number) => {
  if (!video.value) return
  const dur = Number(video.value.duration) || 0
  try {
    await historyApi.addHistory('video', video.value.hash, progress, dur, {
      title: video.value.title,
      thumbnail: video.value.thumbnail,
    })
  } catch (e) {
    // 历史上报失败不影响播放，静默忽略
  }
}

// 添加到观看历史（进入播放页时记录一次，进度为 0）
const addToHistory = async () => {
  await reportHistory(0)
}

// 增加观看次数
const incrementViewCount = async () => {
  try {
    // 调用API增加观看次数
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    await fetch(`/api/video/${videoHash.value}/view`, { method: 'POST', headers })
  } catch (e) {
    console.error('增加观看次数失败:', e)
  }
}

const handleLike = async () => {
  if (!video.value) return
  const response = await videoStore.likeVideo(video.value.hash) as any
  if (response && response.like_count !== undefined) {
    video.value.like_count = response.like_count
    isLiked.value = response.liked
  }
}

const handleFavorite = async () => {
  if (!video.value) return
  const response = await videoStore.favoriteVideo(video.value.hash) as any
  if (response && response.favorite_count !== undefined) {
    video.value.favorite_count = response.favorite_count
    isFavorited.value = response.favorited
  }
  // 显示提示
  const message = isFavorited.value ? '已添加到收藏' : '已取消收藏'
  showToast(message)
}

const handleDislike = async () => {
  if (!video.value) return
  // 踩和点赞互斥：如果当前是点赞状态，先取消点赞（同步后端）
  if (isLiked.value) {
    const r = await videoStore.likeVideo(video.value.hash) as any
    isLiked.value = r?.liked ?? false
    if (video.value) video.value.like_count = r?.like_count ?? video.value.like_count
  }
  // 调用后端切换不喜欢状态
  const response = await videoStore.dislikeVideo(video.value.hash) as any
  if (response && response.success) {
    isDisliked.value = response.disliked
  } else {
    // 请求失败则仅本地切换兜底
    isDisliked.value = !isDisliked.value
  }
  // 显示提示
  const message = isDisliked.value ? '已屏蔽，将不再出现在列表中' : '已取消屏蔽'
  showToast(message)
}

// 提示消息
const toastMessage = ref('')
const showToastFlag = ref(false)
const showToast = (message: string) => {
  toastMessage.value = message
  showToastFlag.value = true
  setTimeout(() => {
    showToastFlag.value = false
  }, 2000)
}

const goBack = () => {
  // 记录刚看过的视频，返回首页后将其置顶到随机推荐的第一个
  if (video.value?.hash) {
    try { sessionStorage.setItem('lastViewedVideo', video.value.hash) } catch {}
  }
  // 优先使用 from 参数回到正确的首页状态
  if (route.query.from) {
    try {
      const homeQuery = JSON.parse(atob(route.query.from as string))
      router.push({ name: 'Home', query: homeQuery })
    } catch {
      // 解码失败，直接回首页
      router.push({ name: 'Home' })
    }
  } else {
    router.push({ name: 'Home' })
  }
}

// 播放事件 - 用于共享观看同步
const onPlay = () => {
  isPlaying.value = true
  showControlsTemporarily()
  // 共享模式下立即同步播放状态
  if (isSharedMode.value && shareCode.value && videoPlayer.value) {
    lastSyncedPlaying.value = true
    lastSyncedTime.value = videoPlayer.value.currentTime
    syncPlaybackState(true)
  }
}

const onPause = () => {
  isPlaying.value = false
  isBuffering.value = false
  showControls.value = true
  netSpeed.value = 0
  stopSpeedMonitor()
  if (controlsTimer) window.clearTimeout(controlsTimer)
  // 共享模式下立即同步播放状态
  if (isSharedMode.value && shareCode.value && videoPlayer.value) {
    lastSyncedPlaying.value = false
    lastSyncedTime.value = videoPlayer.value.currentTime
    syncPlaybackState(true)
  }
}

// ===== 移动端触摸手势：单击/双击切换播放，左右滑动快进快退 =====
const SEEK_SENSITIVITY = 0.4 // 滑动一屏宽度约等于 40% 总时长

const onGestureStart = (e: TouchEvent) => {
  const t = e.touches[0]
  if (!t) return
  touchStartX.value = t.clientX
  touchStartY.value = t.clientY
  touchStartCurrent.value = videoPlayer.value?.currentTime || 0
  touchMoved.value = false
}

const onGestureMove = (e: TouchEvent) => {
  if (!videoPlayer.value) return
  const t = e.touches[0]
  if (!t) return
  const dx = t.clientX - touchStartX.value
  const dy = t.clientY - touchStartY.value
  if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return
  if (Math.abs(dx) > Math.abs(dy)) {
    // 水平滑动：快进 / 快退
    touchMoved.value = true
    const ratio = dx / window.innerWidth
    const delta = ratio * videoDuration.value * SEEK_SENSITIVITY
    const target = Math.max(0, Math.min(videoDuration.value, touchStartCurrent.value + delta))
    videoPlayer.value.currentTime = target
    const sign = delta >= 0 ? '快进' : '快退'
    seekFeedbackText.value = `${sign} ${Math.abs(Math.round(delta))} 秒`
    seekFeedbackVisible.value = true
    if (seekFeedbackTimer) clearTimeout(seekFeedbackTimer)
  } else {
    // 垂直滑动：标记为已移动，避免误触发播放/暂停
    touchMoved.value = true
  }
}

const onGestureEnd = () => {
  if (touchMoved.value) {
    if (seekFeedbackTimer) clearTimeout(seekFeedbackTimer)
    seekFeedbackTimer = window.setTimeout(() => {
      seekFeedbackVisible.value = false
    }, 500)
    touchMoved.value = false
    return
  }
  // 轻触：用定时器区分单击与双击
  const now = Date.now()
  if (now - lastTapTime.value < 300) {
    // 双击：切换播放/暂停
    if (tapTimer.value) {
      clearTimeout(tapTimer.value)
      tapTimer.value = null
    }
    togglePlay()
    lastTapTime.value = 0
  } else {
    // 单击：切换操作栏显示/隐藏，不暂停视频
    lastTapTime.value = now
    if (tapTimer.value) clearTimeout(tapTimer.value)
    tapTimer.value = window.setTimeout(() => {
      if (controlsTimer) window.clearTimeout(controlsTimer)
      showControls.value = !showControls.value
      if (showControls.value && isPlaying.value) {
        // 显示后若正在播放，定时自动隐藏
        controlsTimer = window.setTimeout(() => {
          if (isPlaying.value && !isBuffering.value) showControls.value = false
        }, 3000)
      }
      tapTimer.value = null
    }, 280)
  }
}

const onSeeked = () => {
  // 用户拖动进度条后立即同步
  if (isSharedMode.value && shareCode.value && videoPlayer.value) {
    lastSyncedTime.value = videoPlayer.value.currentTime
    lastSyncedPlaying.value = isPlaying.value
    syncPlaybackState(true)
  }
}

// 格式化时长
const formatDuration = (seconds: number): string => {
  if (!seconds || isNaN(seconds)) return '00:00'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
}

// 下载视频
const handleDownload = async () => {
  if (!video.value) return
  try {
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) {
      headers['Authorization'] = `Bearer ${token}`
    }
    await fetch(`/api/video/${video.value.hash}/download`, { method: 'POST', headers })
    // 创建下载链接
    const link = document.createElement('a')
    link.href = videoUrl.value
    link.download = video.value.title + '.mp4'
    link.click()
  } catch (e) {
    console.error('下载失败:', e)
  }
}

// 分享视频
const handleShare = () => {
  if (!video.value) return
  const shareUrl = `${window.location.origin}/video/${video.value.hash}`
  navigator.clipboard.writeText(shareUrl)
  showToast('链接已复制到剪贴板')
}

// ========== 共享观看功能 ==========

// 创建共享观看会话
const createSharedWatchSession = async () => {
  if (!video.value) return
  
  try {
    const token = localStorage.getItem('token')
    if (!token) {
      showToast('请先登录')
      return
    }
    
    const response = await fetch('/api/shared-watch/create', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ video_hash: video.value.hash })
    })
    
    const data = await response.json()
    
    if (data.success) {
      shareCode.value = data.share_code
      shareUrl.value = `${window.location.origin}/shared/${data.share_code}`
      isSharedMode.value = true
      isCreator.value = true
      showShareDialog.value = true
      startSyncLoop()
      showToast('共享观看链接已创建')
    } else {
      showToast(data.message || '创建失败')
    }
  } catch (e) {
    console.error('创建共享观看失败:', e)
    showToast('创建失败')
  }
}

// 加入共享观看会话
const joinSharedWatchSession = async (code: string) => {
  try {
    const token = localStorage.getItem('token')
    if (!token) {
      showToast('请先登录')
      return false
    }
    
    const response = await fetch(`/api/shared-watch/${code}/join`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    
    const data = await response.json()
    
    if (data.success) {
      shareCode.value = code
      isSharedMode.value = true
      isCreator.value = data.is_creator
      sharedSession.value = data.session
      
      // 同步到当前播放进度
      if (videoPlayer.value && data.session.current_time > 0) {
        videoPlayer.value.currentTime = data.session.current_time
      }
      if (data.session.is_playing && videoPlayer.value) {
        videoPlayer.value.play()
      } else if (videoPlayer.value) {
        videoPlayer.value.pause()
      }
      
      startSyncLoop()
      showToast('已加入共享观看')
      return true
    } else {
      showToast(data.message || '加入失败')
      return false
    }
  } catch (e) {
    console.error('加入共享观看失败:', e)
    showToast('加入失败')
    return false
  }
}

// 检查是否是共享链接访问
const checkSharedLink = async () => {
  const path = window.location.pathname
  const match = path.match(/^\/shared\/([a-zA-Z0-9]+)$/)
  
  if (match) {
    const code = match[1]
    
    // 先获取会话信息（无需登录）
    try {
      const infoResponse = await fetch(`/api/shared-watch/${code}/info`)
      const infoData = await infoResponse.json()
      
      if (!infoData.success || !infoData.is_shared) {
        showToast(infoData.message || '链接已失效')
        router.push('/')
        return
      }
      
      // 跳转到视频页面
      router.push(`/video/${infoData.video_hash}`)
      
      // 尝试加入会话
      const token = localStorage.getItem('token')
      if (token) {
        await joinSharedWatchSession(code)
      } else {
        showToast('请先登录以加入共享观看')
      }
    } catch (e) {
      console.error('检查共享链接失败:', e)
      router.push('/')
    }
  }
}

// 开始同步循环
const startSyncLoop = () => {
  if (syncInterval.value) return

  // 每500ms同步一次（从2秒降低到500ms，减少延迟）
  syncInterval.value = window.setInterval(async () => {
    if (!isSharedMode.value || !shareCode.value) return

    // 同步本地播放状态到服务器
    if (videoPlayer.value) {
      await syncPlaybackState()
    }

    // 获取远程播放状态
    await fetchPlaybackState()
  }, 500)
}

// 停止同步循环
const stopSyncLoop = () => {
  if (syncInterval.value) {
    clearInterval(syncInterval.value)
    syncInterval.value = null
  }
}

// 同步播放状态到服务器
const lastSyncedTime = ref(0)
const lastSyncedPlaying = ref(false)

const syncPlaybackState = async (force = false) => {
  if (!shareCode.value || !videoPlayer.value) return

  const token = localStorage.getItem('token')
  if (!token) return

  // 只在状态变化时才同步（时间差>1秒或播放状态改变），除非强制同步
  const timeDiff = Math.abs(videoPlayer.value.currentTime - lastSyncedTime.value)
  const playingChanged = isPlaying.value !== lastSyncedPlaying.value

  if (!force && timeDiff < 1 && !playingChanged) {
    return // 没有显著变化，跳过同步
  }

  try {
    await fetch(`/api/shared-watch/${shareCode.value}/sync`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({
        current_time: videoPlayer.value.currentTime,
        is_playing: isPlaying.value,
        timestamp: Date.now() // 添加时间戳，用于补偿网络延迟
      })
    })

    lastSyncedTime.value = videoPlayer.value.currentTime
    lastSyncedPlaying.value = isPlaying.value
    lastSyncTime.value = videoPlayer.value.currentTime
  } catch (e) {
    console.error('同步播放状态失败:', e)
  }
}

// 获取远程播放状态
const fetchPlaybackState = async () => {
  if (!shareCode.value || !videoPlayer.value) return
  
  const token = localStorage.getItem('token')
  if (!token) return
  
  try {
    const response = await fetch(`/api/shared-watch/${shareCode.value}/state`, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    
    const data = await response.json()
    
    if (data.success) {
      // 同步播放进度（只在差异较大时跳转）
      const timeDiff = Math.abs(videoPlayer.value.currentTime - data.current_time)
      if (timeDiff > 3) {
        videoPlayer.value.currentTime = data.current_time
      }
      
      // 同步播放/暂停状态
      if (data.is_playing && !isPlaying.value) {
        videoPlayer.value.play()
      } else if (!data.is_playing && isPlaying.value) {
        videoPlayer.value.pause()
      }
    }
  } catch (e) {
    console.error('获取播放状态失败:', e)
  }
}

// 结束共享观看会话
const endSharedWatchSession = async () => {
  if (!shareCode.value) return
  
  const token = localStorage.getItem('token')
  if (!token) return
  
  try {
    await fetch(`/api/shared-watch/${shareCode.value}/end`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    })
    
    stopSyncLoop()
    isSharedMode.value = false
    shareCode.value = ''
    shareUrl.value = ''
    sharedSession.value = null
    showToast('共享观看已结束')
  } catch (e) {
    console.error('结束共享观看失败:', e)
  }
}

// 复制共享链接
const copyShareUrl = () => {
  navigator.clipboard.writeText(shareUrl.value)
  showToast('链接已复制到剪贴板')
}

// 页面卸载时停止同步
onUnmounted(() => {
  stopSyncLoop()
  clearAutoContinueTimer()
  document.removeEventListener('click', onDocClickCloseMenu)
  window.removeEventListener('resize', updateMobileState)
  document.removeEventListener('fullscreenchange', updateFullscreenState)
})

// 打开编辑抽屉（管理员可编辑标题/简介/资源库/标签）
const openEditDrawer = () => {
  if (!video.value) return
  editingItem.value = video.value
  editDrawerVisible.value = true
}

// 抽屉保存后就地更新当前视频信息
const onEditSaved = (updated: any) => {
  if (!video.value) return
  video.value = { ...video.value, ...updated }
}

// 资源隐藏 / 显示切换（仅管理员）：隐藏后不出现在视频库列表，仅在帖子流可见
const togglingHidden = ref(false)
const moreMenuOpen = ref(false)
const isHidden = computed(() => !!video.value?.hidden)
async function toggleHidden() {
  if (!video.value || togglingHidden.value) return
  const rid = video.value.resource_index_id
  if (!rid) return
  togglingHidden.value = true
  try {
    const res = await resourceApi.setHidden(rid, !isHidden.value)
    video.value = { ...video.value, hidden: res.hidden }
  } catch (e) {
    console.error('切换隐藏状态失败', e)
  } finally {
    togglingHidden.value = false
  }
}

// ============ 精彩片段标记 ============
const formatMarkerTime = (sec: number) => {
  const s = Math.max(0, Math.floor(sec))
  const m = Math.floor(s / 60)
  const r = s % 60
  return `${m}:${r.toString().padStart(2, '0')}`
}

const loadMarkers = async () => {
  if (!video.value) return
  try {
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`/api/video/${video.value.hash}/markers`, { headers })
    if (res.ok) markers.value = await res.json()
  } catch (e) {
    console.error('加载精彩片段标记失败', e)
  }
}

const startAddMarker = () => {
  markerNote.value = ''
  showMarkerForm.value = true
}

const cancelAddMarker = () => {
  showMarkerForm.value = false
  markerNote.value = ''
}

const submitMarker = async () => {
  if (!video.value) return
  const time = videoPlayer.value?.currentTime ?? 0
  try {
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`/api/video/${video.value.hash}/markers`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ time, note: markerNote.value.trim() }),
    })
    if (res.ok) {
      await loadMarkers()
      cancelAddMarker()
    }
  } catch (e) {
    console.error('添加精彩片段标记失败', e)
  }
}

const jumpToMarker = (time: number) => seekTo(time)

const deleteMarker = async (id: number) => {
  if (!video.value) return
  try {
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = {}
    if (token) headers['Authorization'] = `Bearer ${token}`
    const res = await fetch(`/api/video/${video.value.hash}/markers/${id}`, {
      method: 'DELETE',
      headers,
    })
    if (res.ok) markers.value = markers.value.filter(m => m.id !== id)
  } catch (e) {
    console.error('删除精彩片段标记失败', e)
  }
}

let lastReportTime = 0
const durationLoaded = ref(0)
const onLoadedMetadata = () => {
  // 元信息加载完成，强制 videoDuration 重新计算（读取 <video> 元素真实时长）
  durationLoaded.value++
}
const onTimeUpdate = () => {
  if (videoPlayer.value) currentTime.value = videoPlayer.value.currentTime
  // 每 10 秒上报一次观看进度（节流，避免频繁请求）
  const now = Date.now()
  if (now - lastReportTime > 10000 && videoDuration.value > 0) {
    lastReportTime = now
    const p = currentTime.value / videoDuration.value
    reportHistory(Math.min(1, Math.max(0, p)))
  }
}

// ============ 标签编辑器 ============
const showTagEditor = ref(false)  // 是否显示标签编辑器
const tagInput = ref('')  // 当前输入的标签
const tagSuggestions = ref<Tag[]>([])  // 标签建议列表
const showTagSuggestions = ref(false)  // 是否显示建议下拉框
const tagInputRef = ref<HTMLInputElement | null>(null)
const editingTagId = ref<number | null>(null)  // 正在编辑的标签ID
const editingTagPath = ref('')  // 正在编辑的标签路径
const selectedTagPath = ref('')  // 从树中选择的标签路径前缀
const allTagsTree = ref<any[]>([])  // 所有标签的树形结构
const currentTagLevel = ref<any[]>([])  // 当前显示的标签层级
const filteredTagLevel = ref<any[]>([])  // 过滤后的标签层级（输入时使用）
const tagBreadcrumbs = ref<any[]>([])  // 面包屑导航
const isTagFiltered = ref(false)  // 是否处于过滤状态

// 打开标签编辑器
const openTagEditor = async () => {
  // 暂停视频播放，防止视频覆盖对话框
  if (videoPlayer.value) {
    videoPlayer.value.pause()
    // 移除视频src，防止夸克等浏览器劫持视频导致覆盖对话框
    const originalSrc = videoPlayer.value.src
    videoPlayer.value.dataset.originalSrc = originalSrc
    videoPlayer.value.src = ''
    videoPlayer.value.dataset.restoreSrc = originalSrc
  }
  showTagEditor.value = true
  tagInput.value = ''
  tagSuggestions.value = []
  showTagSuggestions.value = false
  selectedTagPath.value = ''
  editingTagId.value = null
  editingTagPath.value = ''
  tagBreadcrumbs.value = []
  // 加载所有标签树
  await loadAllTagsTree()
  // 锁定背景滚动，防止手机端可以滑动页面
  document.body.style.overflow = 'hidden'
}

// 关闭标签编辑器
const closeTagEditor = () => {
  // 恢复视频src
  if (videoPlayer.value && videoPlayer.value.dataset.restoreSrc) {
    videoPlayer.value.src = videoPlayer.value.dataset.restoreSrc
  }
  showTagEditor.value = false
  tagInput.value = ''
  tagSuggestions.value = []
  showTagSuggestions.value = false
  editingTagId.value = null
  editingTagPath.value = ''
  selectedTagPath.value = ''
  tagBreadcrumbs.value = []
  // 恢复背景滚动
  document.body.style.overflow = ''
}

// 加载所有标签构建树形结构
const loadAllTagsTree = async () => {
  try {
    const libraryId = video.value?.library_id
    const params = new URLSearchParams()
    if (libraryId) params.append('library_id', String(libraryId))
    const response = await fetch(`/api/tags/all?${params}`)
    const data = await response.json()
    if (data.tags) {
      allTagsTree.value = buildTagTree(data.tags)
      // 初始显示根级别
      currentTagLevel.value = allTagsTree.value
    }
  } catch (e) {
    console.error('加载标签树失败:', e)
  }
}

// 构建标签树形结构
const buildTagTree = (tags: Tag[]): any[] => {
  const tagMap = new Map<number, any>()
  const rootTags: any[] = []

  // 先创建所有节点
  tags.forEach(tag => {
    tagMap.set(tag.id, { ...tag, children: [] })
  })

  // 构建树形结构
  tags.forEach(tag => {
    const node = tagMap.get(tag.id)!
    if (tag.parent_id && tagMap.has(tag.parent_id)) {
      tagMap.get(tag.parent_id)!.children.push(node)
    } else {
      rootTags.push(node)
    }
  })

  return rootTags
}

// 从树中选择标签（进入子层级或选中）
const selectTagFromTree = (tag: any) => {
  if (tag.children && tag.children.length > 0) {
    // 有子标签，进入该层级
    currentTagLevel.value = tag.children
    // 添加到面包屑
    tagBreadcrumbs.value.push({ id: tag.id, name: tag.name, path: tag.path || tag.name })
  } else {
    // 没有子标签，选中该标签
    selectedTagPath.value = tag.path || tag.name
    tagInput.value = ''
  }
}

// 返回上一级
const goBackTagLevel = () => {
  if (tagBreadcrumbs.value.length > 0) {
    tagBreadcrumbs.value.pop()
    if (tagBreadcrumbs.value.length === 0) {
      currentTagLevel.value = allTagsTree.value
    } else {
      // 找到上一级的子标签
      const parentPath = tagBreadcrumbs.value.map(b => b.name).join('/')
      const findLevel = (tags: any[], path: string): any[] => {
        for (const tag of tags) {
          if ((tag.path || tag.name) === path && tag.children) {
            return tag.children
          }
          if (tag.children) {
            const found = findLevel(tag.children, path)
            if (found) return found
          }
        }
        return null
      }
      const level = findLevel(allTagsTree.value, parentPath)
      currentTagLevel.value = level || allTagsTree.value
    }
  }
}

// 返回根级别
const goToRootLevel = () => {
  tagBreadcrumbs.value = []
  currentTagLevel.value = allTagsTree.value
}

// 插入分隔符
const insertSlash = () => {
  if (editingTagId.value !== null) {
    editingTagPath.value += '/'
  } else {
    tagInput.value += '/'
  }
}

// 渲染路径分隔符（返回路径各部分）
const renderPathParts = (path: string): string[] => {
  if (!path) return []
  return path.split('/').filter(p => p.trim())
}

// 搜索标签 - 根据输入关键词匹配（支持从任意层级匹配）
// 从标签树中提取所有标签路径（扁平化）
const flattenTags = (tree: any[]): string[] => {
  const paths: string[] = []
  const traverse = (nodes: any[]) => {
    for (const node of nodes) {
      if (node.path) {
        paths.push(node.path)
      }
      if (node.children && node.children.length > 0) {
        traverse(node.children)
      }
    }
  }
  traverse(tree)
  return paths
}

// 从 allTagsTree 中过滤匹配的标签（本地过滤）
const filterTagsLocally = (keyword: string): Tag[] => {
  if (!keyword.trim() || allTagsTree.value.length === 0) {
    return []
  }
  const lowerKeyword = keyword.toLowerCase()
  const allPaths = flattenTags(allTagsTree.value)
  const matchedPaths = allPaths.filter(path =>
    path.toLowerCase().includes(lowerKeyword)
  )
  // 去重并构建 Tag 对象
  const seen = new Set<string>()
  const result: Tag[] = []
  for (const path of matchedPaths) {
    if (!seen.has(path)) {
      seen.add(path)
      result.push({
        id: 0,
        name: path.split('/').pop() || path,
        path: path,
        category: '',
        parent_id: null,
        library_id: null
      })
    }
  }
  return result
}

// 搜索标签（本地 + 后端API）
const searchTags = async (keyword: string) => {
  if (!keyword.trim()) {
    tagSuggestions.value = []
    return
  }

  // 先尝试本地过滤（基于已加载的标签树）
  const localResults = filterTagsLocally(keyword)
  if (localResults.length > 0) {
    tagSuggestions.value = localResults
  }

  // 同时调用后端API获取更多结果
  try {
    const libraryId = video.value?.library_id
    const response = await tagApi.searchTags(keyword, libraryId || undefined) as any
    if (response.success && response.tags) {
      // 合并结果，去重
      const existingPaths = new Set(tagSuggestions.value.map((t: Tag) => t.path))
      for (const tag of response.tags) {
        if (!existingPaths.has(tag.path)) {
          tagSuggestions.value.push(tag)
          existingPaths.add(tag.path)
        }
      }
    }
  } catch (e) {
    // API失败时只依赖本地结果
    console.error('搜索标签API失败:', e)
  }
}

// 从标签树中过滤匹配的标签（扁平列表，不保留树状结构）
const filterTagTreeLocally = (keyword: string): Tag[] => {
  if (!keyword.trim() || allTagsTree.value.length === 0) {
    return []
  }
  const lowerKeyword = keyword.toLowerCase()
  const result: Tag[] = []
  const seen = new Set<string>()

  // 递归收集所有匹配的标签路径
  const collectMatches = (nodes: any[]) => {
    for (const node of nodes) {
      const nameMatch = node.name.toLowerCase().includes(lowerKeyword)
      const pathMatch = (node.path || '').toLowerCase().includes(lowerKeyword)

      if (nameMatch || pathMatch) {
        const path = node.path || node.name
        if (!seen.has(path)) {
          seen.add(path)
          result.push({
            id: node.id,
            name: node.name,
            path: path,
            category: node.category || '',
            parent_id: node.parent_id,
            library_id: node.library_id
          })
        }
      }

      // 继续搜索子节点
      if (node.children) {
        collectMatches(node.children)
      }
    }
  }

  collectMatches(allTagsTree.value)
  return result
}

// 标签输入处理
const onTagInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  const value = target.value

  // 如果正在编辑某个标签
  if (editingTagId.value !== null) {
    editingTagPath.value = value
    // 编辑模式下也支持搜索建议
    searchTags(value)
    showTagSuggestions.value = value.trim().length > 0
    return
  }

  tagInput.value = value

  if (value.trim()) {
    // 过滤左侧标签树
    const filtered = filterTagTreeLocally(value)
    filteredTagLevel.value = filtered
    isTagFiltered.value = filtered.length > 0

    searchTags(value)
    showTagSuggestions.value = true
  } else {
    // 恢复原始标签树
    filteredTagLevel.value = []
    isTagFiltered.value = false
    tagSuggestions.value = []
    showTagSuggestions.value = false
  }
}

// 选择标签建议
const selectTagSuggestion = (tag: Tag) => {
  if (editingTagId.value !== null) {
    // 编辑模式：更新标签路径
    editingTagPath.value = tag.path
    tagSuggestions.value = []
    showTagSuggestions.value = false
  } else {
    // 添加模式：设置为当前路径前缀
    selectedTagPath.value = tag.path || tag.name
    tagInput.value = ''
    tagSuggestions.value = []
    showTagSuggestions.value = false
  }
}

// 选择过滤结果中的标签（填入输入框，方便继续编辑）
const selectFilteredTag = (tag: Tag) => {
  // 将完整路径填入输入框，方便用户继续编辑
  tagInput.value = tag.path || tag.name
  selectedTagPath.value = ''
  // 保持过滤状态，让用户可以继续修改
  searchTags(tagInput.value)
}

// 隐藏建议框
const hideTagSuggestions = () => {
  setTimeout(() => {
    showTagSuggestions.value = false
  }, 200)
}

// 清除标签过滤，恢复原始标签树
const clearTagFilter = () => {
  tagInput.value = ''
  filteredTagLevel.value = []
  isTagFiltered.value = false
  tagSuggestions.value = []
  showTagSuggestions.value = false
  currentTagLevel.value = allTagsTree.value
  tagBreadcrumbs.value = []
}

// 处理输入框失去焦点
const onTagInputFocusOut = (event: FocusEvent) => {
  const relatedTarget = event.relatedTarget as HTMLElement
  // 如果焦点转移到推荐框或slash按钮，不隐藏推荐框
  if (relatedTarget && (relatedTarget.classList.contains('tag-suggestion-item') || relatedTarget.classList.contains('slash-btn'))) {
    return
  }
  showTagSuggestions.value = false
}

// 标签补充项（qualifiers）：每个视频标签可勾选其预设补充项
const tagQualifiers = reactive<Record<number, string[]>>({})
// 每个标签的“新建补充项”输入框内容（按 tag.id 区分）
const newQualifierInput = reactive<Record<number, string>>({})

const initTagQualifiers = () => {
  if (!video.value?.tags) return
  for (const t of video.value.tags) {
    tagQualifiers[t.id] = Array.isArray(t.selected_qualifiers) ? [...t.selected_qualifiers] : []
  }
}

// 视频标签变化时重新初始化补充项选择
watch(() => video.value?.tags, () => initTagQualifiers(), { immediate: true })

const toggleQualifier = (tagId: number, q: string) => {
  if (!tagQualifiers[tagId]) tagQualifiers[tagId] = []
  const arr = tagQualifiers[tagId]
  const i = arr.indexOf(q)
  if (i === -1) arr.push(q)
  else arr.splice(i, 1)
  // 切换后立即持久化整组标签（含补充项）
  saveTagQualifiers()
}

// 仅保存补充项勾选状态（不影响路径/增删）
const saveTagQualifiers = async () => {
  if (!video.value) return
  try {
    const token = localStorage.getItem('token')
    const payload = buildTagPayload()
    const response = await fetch(`/api/video/${video.value.hash}/tags`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ tags: payload })
    })
    if (response.ok) {
      const data = await response.json() as { tags?: Array<{ id: number; selected_qualifiers?: string[] }> }
      const map = new Map((data.tags || []).map(t => [t.id, t.selected_qualifiers || []]))
      for (const t of (video.value.tags || [])) {
        if (map.has(t.id)) t.selected_qualifiers = map.get(t.id)
      }
    }
  } catch (e) {
    console.error('保存补充项失败:', e)
  }
}

// 新建补充项：先写入标签的全局预设池（仅管理员可写），再勾选到当前视频并持久化
const addQualifier = async (tag: VideoTagRef, rawQ: string) => {
  const q = (rawQ || '').trim()
  if (!q) return
  newQualifierInput[tag.id] = ''
  const pool = tag.qualifiers || []
  // 若不在预设池中，则追加到该标签的全局补充项池
  if (!pool.includes(q)) {
    const nextPool = [...pool, q]
    try {
      const res = await tagApi.updateTag(tag.id, { qualifiers: nextPool }) as any
      tag.qualifiers = (res?.success && res.tag?.qualifiers) ? res.tag.qualifiers : nextPool
    } catch (e) {
      console.error('新增补充项到标签池失败:', e)
      tag.qualifiers = nextPool
    }
  }
  // 勾选到当前视频
  const selected = tagQualifiers[tag.id] || []
  if (!selected.includes(q)) tagQualifiers[tag.id] = [...selected, q]
  await saveTagQualifiers()
}

// 构建提交负载：所有标签转为 { path, qualifiers } 对象
const buildTagPayload = () => {
  return (video.value?.tags || []).map(t => ({
    path: t.path || t.name,
    qualifiers: tagQualifiers[t.id] || []
  }))
}

// 开始编辑标签
const startEditTag = (tag: Tag) => {
  editingTagId.value = tag.id
  editingTagPath.value = tag.path || tag.name
  showTagSuggestions.value = false
}

// 取消编辑标签
const cancelEditTag = () => {
  editingTagId.value = null
  editingTagPath.value = ''
}

// 保存标签编辑
const saveTagEdit = async () => {
  if (!video.value || editingTagId.value === null) return

  const newPath = editingTagPath.value.trim()
  if (!newPath) {
    cancelEditTag()
    return
  }

  try {
    const token = localStorage.getItem('token')
    // 构建全部标签负载（含补充项），替换正在编辑的标签路径
    const currentTags = buildTagPayload()
    const editTag = video.value!.tags?.find(vt => vt.id === editingTagId.value)
    if (editTag) {
      const idx = currentTags.findIndex(c => c.path === (editTag.path || editTag.name))
      if (idx !== -1) {
        currentTags[idx] = { path: newPath, qualifiers: tagQualifiers[editTag.id] || [] }
      }
    }

    const response = await fetch(`/api/video/${video.value.hash}/tags`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ tags: currentTags })
    })

    if (response.ok) {
      // 重新获取视频信息
      await refreshVideo()
    }

    cancelEditTag()
  } catch (e) {
    console.error('保存标签失败:', e)
  }
}

// 删除标签
const deleteTag = async (tag: Tag) => {
  if (!video.value) return

  try {
    const token = localStorage.getItem('token')
    const response = await fetch(`/api/video/${video.value.hash}/tags`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ tag_path: tag.path || tag.name })
    })

    if (response.ok) {
      // 重新获取视频信息
      await refreshVideo()
      // 刷新标签树
      await loadAllTagsTree()
    }
  } catch (e) {
    console.error('删除标签失败:', e)
  }
}

// 查看模式下快捷删除标签（已移至标签树对话框处理）

// 确认添加标签（输入框回车或点击添加按钮）
const confirmAddTag = async () => {
  if (!video.value) return

  // 组合完整路径：selectedTagPath + tagInput
  let newTag = ''
  if (selectedTagPath.value) {
    newTag = selectedTagPath.value + (tagInput.value.trim() ? '/' + tagInput.value.trim() : '')
  } else {
    newTag = tagInput.value.trim()
  }

  if (!newTag) {
    // 空输入取消操作
    tagInput.value = ''
    return
  }

  try {
    const token = localStorage.getItem('token')
    // 构建全部标签负载（含补充项），追加新标签
    const payload = buildTagPayload()
    if (!payload.some(p => p.path === newTag)) {
      payload.push({ path: newTag, qualifiers: [] })
    }

    const response = await fetch(`/api/video/${video.value.hash}/tags`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify({ tags: payload })
    })

    if (response.ok) {
      tagInput.value = ''
      selectedTagPath.value = ''
      await refreshVideo()
      // 刷新标签树
      await loadAllTagsTree()
    }
  } catch (e) {
    console.error('添加标签失败:', e)
  }
}

// 重新获取视频信息
const refreshVideo = async () => {
  if (!video.value) return
  const response = await videoStore.fetchVideo(video.value.hash)
  if (response && response.video) {
    video.value = response.video
  }
}

// 删除视频
const showDeleteConfirm = ref(false)
const deleteFileOption = ref(false)  // 是否同时删除文件

const confirmDelete = () => {
  deleteFileOption.value = false
  showDeleteConfirm.value = true
}

const handleDelete = async () => {
  if (!video.value) return

  try {
    await videoStore.deleteVideo(video.value.hash, deleteFileOption.value)
    router.push('/')
  } catch (e) {
    alert('删除失败')
  }
}
</script>

<template>
  <div class="video-page">
    <!-- 返回按钮 -->
    <button class="back-btn" @click="goBack">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 12H5M12 19l-7-7 7-7"/>
      </svg>
      返回
    </button>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container" data-testid="video-loading">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 视频内容 -->
    <div v-else-if="video" class="video-content">
      <div class="video-main">
        <!-- 视频播放器区域 -->
        <div class="player-section">
          <div class="video-player-container" data-testid="video-player" :class="{ 'hide-on-mobile': showTagEditor }">
            <!-- PC 端竖屏全屏入口（移动端用底部控制栏的按钮） -->
            <button
              v-if="!isMobile"
              class="portrait-entry-pc"
              @click.stop="enterPortraitMode"
              title="竖屏全屏"
              aria-label="竖屏全屏"
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <rect x="7" y="2" width="10" height="20" rx="2" />
                <line x1="11" y1="18" x2="13" y2="18" />
              </svg>
            </button>
            <!-- 精彩片段标记进度条 -->
            <div class="marker-track" v-if="markerTrack.length" @click.stop>
              <div
                v-for="mk in markerTrack"
                :key="mk.id"
                class="marker-tick"
                :style="{ left: mk.left + '%' }"
                :title="`${formatMarkerTime(mk.time)} · ${mk.note}`"
                @click.stop="seekTo(mk.time)"
              >
                <span class="marker-tip">{{ mk.note }}</span>
              </div>
            </div>
            <video
              ref="videoPlayer"
              :src="videoUrl"
              class="video-element"
              playsinline
              webkit-playsinline
              x5-playsinline
              x5-video-player-type="h5-page"
              x5-video-player-fullscreen="true"
              @play="onPlay"
              @pause="onPause"
              @seeked="onSeeked"
              @timeupdate="onTimeUpdate"
              @loadedmetadata="onLoadedMetadata"
              @waiting="onWaiting"
              @playing="onPlaying"
              @stalled="onStalled"
              @ended="onVideoEnded"
              preload="metadata"
              :controls="!isMobile"
            ></video>
            <!-- 缓冲转圈 + 网速 -->
            <div v-if="isBuffering" class="buffering-overlay">
              <div class="buffering-spinner"></div>
              <div class="buffering-speed" v-if="netSpeed > 0">{{ formatSpeed(netSpeed) }}/s</div>
            </div>
            <!-- 移动端手势层：双击/左右滑动控制播放进度 -->
            <div
              v-if="isTouchMode"
              class="gesture-layer"
              @touchstart="onGestureStart"
              @touchmove.prevent="onGestureMove"
              @touchend="onGestureEnd"
            ></div>
            <!-- 快进/快退反馈 -->
            <div v-if="isTouchMode && seekFeedbackVisible" class="seek-feedback">
              {{ seekFeedbackText }}
            </div>
            <!-- 移动端底部控制栏：播放/暂停 + 进度条 + 全屏（原生控件在触摸模式下关闭） -->
            <div
              v-if="isMobile && !autoContinueVisible"
              class="mobile-controls"
              :class="{ hidden: !showControls }"
              @click.stop
            >
              <div
                ref="progressBarRef"
                class="mp-bar"
                @touchstart.prevent="seekFromBar($event)"
                @touchmove.prevent="seekFromBar($event)"
                @click="seekFromBar($event)"
              >
                <div class="mp-played" :style="{ width: (videoDuration ? (currentTime / videoDuration) * 100 : 0) + '%' }"></div>
                <div class="mp-thumb" :style="{ left: (videoDuration ? (currentTime / videoDuration) * 100 : 0) + '%' }"></div>
              </div>
              <div class="mc-row">
                <button class="mc-btn" @click.stop="togglePlay" :aria-label="isPlaying ? '暂停' : '播放'">
                  <svg v-if="!isPlaying" width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                  <svg v-else width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M6 5h4v14H6zM14 5h4v14h-4z" />
                  </svg>
                </button>
                <div class="mp-time">
                  <span>{{ formatTime(currentTime) }}</span>
                  <span>{{ formatTime(videoDuration) }}</span>
                </div>
                <button class="mc-btn" @click.stop="toggleFullscreen" :aria-label="isFullscreen ? '退出全屏' : '全屏'">
                  <svg v-if="!isFullscreen" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3" />
                  </svg>
                  <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3" />
                  </svg>
                </button>
                <!-- 竖屏全屏（短视频沉浸模式）入口 -->
                <button class="mc-btn" @click.stop="enterPortraitMode" :aria-label="'竖屏全屏'" title="竖屏全屏">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="7" y="2" width="10" height="20" rx="2" />
                    <line x1="11" y1="18" x2="13" y2="18" />
                  </svg>
                </button>
              </div>
            </div>
            <!-- 自动续播倒计时遮罩 -->
            <div class="auto-continue-overlay" v-if="autoContinueVisible" @click.stop>
              <div class="ac-card">
                <div class="ac-title">即将播放</div>
                <div class="ac-name">{{ autoContinueTarget?.title || '下一个视频' }}</div>
                <div class="ac-count">{{ autoContinueCountdown }} 秒后自动跳转</div>
                <div class="ac-actions">
                  <button class="ac-btn ac-cancel" @click="cancelAutoContinue">取消</button>
                  <button class="ac-btn ac-now" @click="cancelAutoContinue(); autoContinueTarget && goCollectionItem(autoContinueTarget)">立即播放</button>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 竖屏全屏短视频模式（抖音式沉浸播放 · 跟手 feed track），Teleport 到 body 避免父级 overflow 裁剪 -->
        <Teleport to="body">
          <div class="portrait-mode" v-if="playMode === 'portrait'" @click="onPortraitTap">
            <!-- 纵向 feed 轨道：prev / current / next 三格，跟手指平移 -->
            <div
              class="portrait-track"
              :class="{ dragging: portraitDragging, animating: portraitTransition }"
              :style="{ transform: `translateY(${portraitTrackY}px)` }"
              @touchstart="onPortraitTouchStart"
              @touchmove.prevent="onPortraitTouchMove"
              @touchend="onPortraitTouchEnd"
            >
              <!-- 上一个（历史）预览 -->
              <div class="portrait-item">
                <div
                  class="portrait-item-cover"
                  v-if="portraitPrevPreview && portraitPrevPreview.cover"
                  :style="{ backgroundImage: `url(${portraitPrevPreview.cover})` }"
                ></div>
                <div class="portrait-item-ph" v-else>
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="rgba(255,255,255,0.25)"><path d="M8 5v14l11-7z"/></svg>
                </div>
                <div class="portrait-item-title" v-if="portraitPrevPreview">{{ portraitPrevPreview.title }}</div>
              </div>

              <!-- 当前视频 -->
              <div class="portrait-item">
                <video
                  ref="portraitPlayer"
                  :src="portraitVideoUrl"
                  class="portrait-video"
                  autoplay
                  playsinline
                  webkit-playsinline
                  x5-playsinline
                  x5-video-player-type="h5-page"
                  @ended="onPortraitEnded"
                  @click.stop
                ></video>
                <!-- 底部视频信息 -->
                <div class="portrait-info" @click.stop>
                  <div class="portrait-title">{{ portraitVideo?.title || video.title }}</div>
                  <div class="portrait-meta" v-if="portraitVideo?.file_name">{{ portraitVideo.file_name }}</div>
                </div>
              </div>

              <!-- 下一个（随机）预览 -->
              <div class="portrait-item">
                <div
                  class="portrait-item-cover"
                  v-if="portraitNextPreview && portraitNextPreview.cover"
                  :style="{ backgroundImage: `url(${portraitNextPreview.cover})` }"
                ></div>
                <div class="portrait-item-ph" v-else>
                  <svg width="40" height="40" viewBox="0 0 24 24" fill="rgba(255,255,255,0.25)"><path d="M8 5v14l11-7z"/></svg>
                </div>
                <div class="portrait-item-title" v-if="portraitNextPreview">{{ portraitNextPreview.title }}</div>
              </div>
            </div>

            <!-- 双击爱心动画 -->
            <transition name="heart-pop">
              <div v-if="showPortraitDoubleLike" class="portrait-heart">
                <svg width="80" height="80" viewBox="0 0 24 24" fill="#ff2d55">
                  <path d="M12 21s-7-4.5-9.5-9C.5 8 2.5 4 6 4c2 0 3.2 1.2 4 2.3C10.8 5.2 12 4 14 4c3.5 0 5.5 4 3.5 8C19 16.5 12 21 12 21z" />
                </svg>
              </div>
            </transition>

            <!-- 右上角：退出 / 横屏全屏 / 详情 -->
            <div class="portrait-top">
              <button class="portrait-top-btn" @click.stop="exitPortraitMode" aria-label="退出竖屏">✕</button>
              <button class="portrait-top-btn" @click.stop="enterLandscapeFromPortrait" aria-label="横屏全屏" title="横屏全屏">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3" />
                </svg>
              </button>
              <button class="portrait-top-btn" @click.stop="openDetailFromPortrait" aria-label="详情" title="详情模式">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <rect x="3" y="4" width="18" height="16" rx="2" />
                  <line x1="3" y1="9" x2="21" y2="9" />
                </svg>
              </button>
            </div>

            <!-- 左上角：不喜欢 -->
            <button class="portrait-dislike-top" :class="{ active: isDisliked }" @click.stop="portraitHandleDislike" aria-label="不喜欢">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="9" />
                <line x1="8" y1="8" x2="16" y2="16" />
                <line x1="16" y1="8" x2="8" y2="16" />
              </svg>
              <span>不喜欢</span>
            </button>

            <!-- 右侧竖排操作栏：点赞 / 收藏 -->
            <div class="portrait-actions">
              <button class="portrait-action" :class="{ active: isLiked }" @click.stop="portraitHandleLike" aria-label="点赞">
                <span class="portrait-action-icon">
                  <svg width="26" height="26" viewBox="0 0 24 24" :fill="isLiked ? '#ff2d55' : 'none'" stroke="currentColor" stroke-width="2">
                    <path d="M12 21s-7-4.5-9.5-9C.5 8 2.5 4 6 4c2 0 3.2 1.2 4 2.3C10.8 5.2 12 4 14 4c3.5 0 5.5 4 3.5 8C19 16.5 12 21 12 21z" />
                  </svg>
                </span>
                <span class="portrait-action-count">{{ portraitVideo?.like_count || 0 }}</span>
              </button>
              <button class="portrait-action" :class="{ active: isFavorited }" @click.stop="portraitHandleFavorite" aria-label="收藏">
                <span class="portrait-action-icon">
                  <svg width="26" height="26" viewBox="0 0 24 24" :fill="isFavorited ? '#ffd60a' : 'none'" stroke="currentColor" stroke-width="2">
                    <path d="M12 17.3l-6.2 3.7 1.6-7L2 9.2l7.1-.6L12 2l2.9 6.6 7.1.6-5.4 4.8 1.6 7z" />
                  </svg>
                </span>
                <span class="portrait-action-count">{{ portraitVideo?.favorite_count || 0 }}</span>
              </button>
            </div>

            <!-- 加载指示 -->
            <div v-if="portraitLoading" class="portrait-loading">
              <div class="buffering-spinner"></div>
            </div>
          </div>
        </Teleport>

        <!-- 合集连播导航条 -->
        <div class="collection-nav" v-if="inCollection">
          <div class="cn-info">
            <span class="cn-label">合集</span>
            <span class="cn-name">{{ collectionName }}</span>
            <span class="cn-progress">{{ currentIndex >= 0 ? currentIndex + 1 : '?' }} / {{ collectionItems.length }}</span>
          </div>
          <div class="cn-actions">
            <button class="cn-btn" :disabled="!prevItem" @click="prevItem && goCollectionItem(prevItem)">← 上一集</button>
            <button class="cn-btn primary" :disabled="!nextItem" @click="nextItem && goCollectionItem(nextItem)">下一集 →</button>
            <button class="cn-btn" @click="router.push(`/collections?c=${collectionId}`)">查看合集</button>
          </div>
        </div>

        <!-- 视频信息区域 -->
        <div class="video-info-section">
        <!-- 查看模式 -->
        <div class="video-title-row">
          <h1 class="video-title" data-testid="video-title">{{ video.title }}</h1>
          <div class="title-actions">
            <!-- 编辑/隐藏等低频操作已收纳至底部"更多"菜单 -->
          </div>
        </div>

        <div class="video-meta">
          <span class="meta-item" data-testid="view-count">{{ video.view_count }} 次观看</span>
          <span class="meta-item">{{ formatDuration(videoDuration || video.duration || 0) }}</span>
          <span class="meta-item" v-if="video.created_at">{{ new Date(video.created_at).toLocaleDateString() }}</span>
          <!-- 合集是分类归属，放在信息区而非操作按钮排 -->
          <span
            v-for="col in videoCollections"
            :key="col.id"
            class="meta-item collection-meta"
            @click="router.push(`/collections?c=${col.id}`)"
            :title="`查看合集：${col.name}`"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="4" width="18" height="4" rx="1"/>
              <rect x="3" y="10" width="18" height="4" rx="1"/>
              <rect x="3" y="16" width="18" height="4" rx="1"/>
            </svg>
            合集：{{ col.name }}
          </span>
        </div>

        <p class="video-description" data-testid="video-description">
          {{ video.description || '暂无描述' }}
        </p>

        <!-- 标签区域 -->
        <div class="video-tags-section">
          <div class="video-tags" data-testid="video-tags" v-if="video.tags && video.tags.length > 0">
            <template v-for="tag in video.tags" :key="'t' + tag.id">
              <span
                v-for="q in (tag.selected_qualifiers && tag.selected_qualifiers.length ? tag.selected_qualifiers : [null])"
                :key="tag.id + '-' + (q || 'base')"
                class="tag-badge"
                @click="filterByTag(tag)"
              >{{ q ? tag.name + '/' + q : tag.name }}</span>
            </template>
          </div>
          <!-- 管理员：添加标签（打开标签树对话框） -->
          <button v-if="canManageVideo" class="tag-add-btn" @click="openTagEditor" title="添加标签">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="12" y1="5" x2="12" y2="19"/>
              <line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
          </button>
          <!-- 合集：与标签同属分类维度，放在标签旁边 -->
          <CollectionPanel item-type="video" :item-hash="(video && video.hash) || videoHash" />
        </div>

        <!-- 精彩片段标记 -->
        <div class="markers-section">
          <div class="markers-header">
            <span class="markers-title">精彩片段</span>
            <button class="markers-add-btn" @click="startAddMarker" :disabled="showMarkerForm">
              + 标记当前位置 ({{ formatMarkerTime(currentTime) }})
            </button>
          </div>

          <div v-if="showMarkerForm" class="marker-form">
            <input
              v-model="markerNote"
              class="marker-note-input"
              type="text"
              placeholder="备注（可选），如：高燃打斗"
              @keyup.enter="submitMarker"
            />
            <button class="marker-save" @click="submitMarker">保存</button>
            <button class="marker-cancel" @click="cancelAddMarker">取消</button>
          </div>

          <div v-if="markers.length" class="markers-list">
            <div
              v-for="m in markers"
              :key="m.id"
              class="marker-item"
              @click="jumpToMarker(m.time_seconds)"
            >
              <span class="marker-time">⏱ {{ formatMarkerTime(m.time_seconds) }}</span>
              <span class="marker-note">{{ m.note || '精彩片段' }}</span>
              <button class="marker-del" @click.stop="deleteMarker(m.id)" title="删除">✕</button>
            </div>
          </div>
          <p v-else class="markers-empty">看到精彩处，点「标记当前位置」记录时间戳，之后随时点击跳转。</p>
        </div>

          <!-- 视频下方交互按钮 -->
          <div class="interaction-bar">
            <!-- 第一行：互动按钮 -->
            <div class="interaction-buttons">
              <!-- 点赞 -->
              <button
                class="interact-btn like-btn"
                :class="{ active: isLiked }"
                @click="handleLike"
                data-testid="like-button"
              >
                <div class="btn-icon">
                  <svg v-if="!isLiked" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                  </svg>
                  <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
                  </svg>
                </div>
                <span class="btn-label">{{ video.like_count || 0 }}</span>
              </button>

              <!-- 收藏 -->
              <button
                class="interact-btn favorite-btn"
                :class="{ active: isFavorited }"
                @click="handleFavorite"
                data-testid="favorite-button"
              >
                <div class="btn-icon">
                  <svg v-if="!isFavorited" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
                  </svg>
                  <svg v-else width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>
                  </svg>
                </div>
                <span class="btn-label">{{ video.favorite_count || 0 }}</span>
              </button>

              <!-- 继续观看（用户主动加入，不自动按打开行为加入） -->
              <button
                class="interact-btn continuewatch-btn"
                :class="{ active: inContinueWatch }"
                @click="toggleContinueWatch"
                data-testid="continue-watch-button"
              >
                <div class="btn-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/>
                  </svg>
                </div>
                <span class="btn-label">{{ inContinueWatch ? '继续观看' : '加入继续' }}</span>
              </button>

              <!-- 共享观看 -->
              <button
                class="interact-btn sharewatch-btn"
                :class="{ active: isSharedMode }"
                @click="isSharedMode ? showShareDialog = true : createSharedWatchSession()"
                data-testid="sharewatch-button"
              >
                <div class="btn-icon">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
                    <circle cx="9" cy="7" r="4"/>
                    <path d="M23 21v-2a4 4 0 0 0-3-3.87"/>
                    <path d="M16 3.13a4 4 0 0 1 0 7.75"/>
                  </svg>
                </div>
                <span class="btn-label">{{ isSharedMode ? '共享中' : '共享' }}</span>
              </button>

              <!-- 下载 -->
              <button class="action-btn" @click="handleDownload" data-testid="download-button">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                  <polyline points="7 10 12 15 17 10"/>
                  <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                <span class="btn-label">下载</span>
              </button>

              <!-- 分享 -->
              <button class="action-btn" @click="handleShare" data-testid="share-button">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <circle cx="18" cy="5" r="3"/>
                  <circle cx="6" cy="12" r="3"/>
                  <circle cx="18" cy="19" r="3"/>
                  <line x1="8.59" y1="13.51" x2="15.42" y2="17.49"/>
                  <line x1="15.41" y1="6.51" x2="8.59" y2="10.49"/>
                </svg>
                <span class="btn-label">分享</span>
              </button>

              <!-- 更多（不常用的操作收进此处，如“不喜欢”） -->
              <div class="more-wrap">
                <button class="action-btn more-btn" @click="showMoreMenu = !showMoreMenu" data-testid="more-button">
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                    <circle cx="5" cy="12" r="2"/>
                    <circle cx="12" cy="12" r="2"/>
                    <circle cx="19" cy="12" r="2"/>
                  </svg>
                  <span class="btn-label">更多</span>
                </button>
                <div v-if="showMoreMenu" class="more-menu" @click.self="showMoreMenu = false">
                  <button
                    v-if="isAdmin"
                    class="more-item"
                    :class="{ active: isHidden }"
                    @click="toggleHidden(); showMoreMenu = false"
                    :disabled="togglingHidden"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                      <line x1="1" y1="1" x2="23" y2="23"/>
                    </svg>
                    <span>{{ isHidden ? '显示资源' : '隐藏资源' }}</span>
                  </button>
                  <button
                    v-if="canManageVideo"
                    class="more-item"
                    @click="openEditDrawer(); showMoreMenu = false"
                    data-testid="edit-video-button"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                    </svg>
                    <span>编辑视频信息</span>
                  </button>
                  <button
                    class="more-item dislike-item"
                    :class="{ active: isDisliked }"
                    @click="handleDislike(); showMoreMenu = false"
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
                    </svg>
                    <span>{{ isDisliked ? '取消不喜欢' : '不喜欢' }}</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- 第二行：管理按钮 - 管理员或本人可见 -->
            <div v-if="canManageVideo" class="action-buttons">
              <button class="action-btn delete-btn" @click="confirmDelete" data-testid="delete-button" title="删除">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  <line x1="10" y1="11" x2="10" y2="17"/>
                  <line x1="14" y1="11" x2="14" y2="17"/>
                </svg>
              </button>
            </div>
          </div>
      </div>

      <!-- 标签编辑器对话框 -->
      <div v-if="showTagEditor" class="dialog-overlay" @click.self="closeTagEditor">
        <div class="dialog tag-editor-dialog">
          <div class="dialog-header">
            <h3>管理标签</h3>
            <button class="close-btn" @click="closeTagEditor">&times;</button>
          </div>

          <div class="tag-editor-body">
            <!-- 左侧：已有标签树 -->
            <div class="tag-tree-panel">
              <div class="panel-title">已有标签</div>

              <!-- 面包屑导航（非过滤状态才显示） -->
              <div class="tag-breadcrumb" v-if="tagBreadcrumbs.length > 0 && !isTagFiltered">
                <span class="breadcrumb-root" @click="goToRootLevel">根</span>
                <template v-for="(crumb, idx) in tagBreadcrumbs" :key="crumb.id">
                  <span class="breadcrumb-sep">/</span>
                  <span
                    class="breadcrumb-item"
                    :class="{ active: idx === tagBreadcrumbs.length - 1 }"
                    @click="goBackTagLevel"
                  >{{ crumb.name }}</span>
                </template>
                <button class="breadcrumb-back" @click="goBackTagLevel" title="返回上级">‹</button>
              </div>

              <div class="tag-tree-container">
                <!-- 过滤状态提示 -->
                <div v-if="isTagFiltered" class="filter-hint">
                  搜索结果：{{ filteredTagLevel.length }} 个匹配标签
                  <button class="clear-filter" @click="clearTagFilter">清除</button>
                </div>

                <!-- 过滤状态：显示扁平列表（直接显示完整路径） -->
                <div v-if="isTagFiltered">
                  <div
                    v-for="tag in filteredTagLevel"
                    :key="tag.id"
                    class="tag-flat-item"
                    :class="{ active: selectedTagPath === tag.path }"
                    @click="selectFilteredTag(tag)"
                  >
                    <span class="tag-flat-path">{{ tag.path }}</span>
                    <span class="tag-flat-check">✓</span>
                  </div>
                </div>

                <!-- 非过滤状态：显示树状层级 -->
                <div v-if="!isTagFiltered">
                  <div
                    v-for="tag in currentTagLevel"
                    :key="tag.id"
                    class="tag-tree-item"
                    :class="{ active: selectedTagPath === tag.path }"
                    @click="selectTagFromTree(tag)"
                  >
                    <span class="tag-tree-name">{{ tag.name }}</span>
                    <span v-if="tag.children && tag.children.length > 0" class="tag-tree-badge">
                      {{ tag.children.length }}
                      <span class="tag-tree-arrow">›</span>
                    </span>
                    <span v-else class="tag-tree-leaf">✓</span>
                  </div>
                  <p v-if="currentTagLevel.length === 0" class="no-tags">该分类下暂无标签</p>
                </div>
              </div>
            </div>

            <!-- 右侧：输入区域 -->
            <div class="tag-input-panel">
              <!-- 当前路径显示 -->
              <div class="current-path-display">
                <span class="path-label">当前路径：</span>
                <span class="path-value" v-if="selectedTagPath || tagInput">
                  <template v-for="(part, idx) in renderPathParts(selectedTagPath + tagInput)" :key="idx">
                    <span v-if="idx > 0" class="path-separator">/</span>
                    <span class="path-part">{{ part }}</span>
                  </template>
                </span>
                <span v-else class="path-placeholder">选择左侧标签或输入新路径</span>
              </div>

              <!-- 输入框区域 -->
              <div class="tag-input-wrapper">
                <input
                  ref="tagInputRef"
                  v-model="tagInput"
                  type="text"
                  class="tag-input"
                  placeholder="输入标签名称"
                  @input="onTagInput"
                  @keydown.enter="confirmAddTag"
                  @focusout="onTagInputFocusOut"
                />
                <button class="slash-btn" @click="insertSlash" title="插入分级符">/</button>
              </div>

              <!-- 标签建议下拉框 -->
              <div v-if="showTagSuggestions && tagSuggestions.length > 0" class="tag-suggestions">
                <div
                  v-for="sTag in tagSuggestions"
                  :key="sTag.id"
                  class="tag-suggestion-item"
                  @click="selectTagSuggestion(sTag)"
                >
                  <span class="suggestion-path">{{ sTag.path }}</span>
                </div>
              </div>

              <!-- 操作按钮 -->
              <div class="tag-input-actions">
                <button class="btn-secondary" @click="closeTagEditor">取消</button>
                <button class="btn-primary" @click="confirmAddTag">添加</button>
              </div>

              <!-- 当前视频的标签列表（可编辑） -->
              <div class="video-tags-list">
                <div class="video-tags-list-header">视频标签</div>
                <div v-if="video.tags && video.tags.length > 0">
                  <div v-for="tag in video.tags" :key="tag.id" class="tag-item">
                    <template v-if="editingTagId === tag.id">
                      <div class="tag-edit-row">
                        <input
                          ref="tagInputRef"
                          v-model="editingTagPath"
                          type="text"
                          class="tag-edit-input"
                          placeholder="输入标签路径"
                          @input="onTagInput"
                          @keydown.enter="saveTagEdit"
                          @keydown.escape="cancelEditTag"
                        />
                        <button class="btn-icon" @click="saveTagEdit" title="保存">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="20 6 9 17 4 12"/>
                          </svg>
                        </button>
                        <button class="btn-icon" @click="cancelEditTag" title="取消">
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <line x1="18" y1="6" x2="6" y2="18"/>
                            <line x1="6" y1="6" x2="18" y2="18"/>
                          </svg>
                        </button>
                      </div>
                    </template>
                    <template v-else>
                      <div class="tag-line">
                        <span class="tag-name">{{ tag.name }}</span>
                        <div class="tag-actions" v-if="canManageVideo">
                        <button class="btn-icon" @click="startEditTag(tag)" title="编辑">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                          </svg>
                        </button>
                        <button class="btn-icon" @click="deleteTag(tag)" title="删除">
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"/>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                          </svg>
                        </button>
                      </div>
                      <div class="tag-qualifiers-edit">
                        <span
                          v-for="q in (tag.qualifiers || [])"
                          :key="q"
                          class="qualifier-chip"
                          :class="{ on: (tagQualifiers[tag.id] || []).includes(q) }"
                          @click="toggleQualifier(tag.id, q)"
                        >{{ q }}</span>
                        <span v-if="isAdmin" class="qualifier-add">
                          <input
                            v-model="newQualifierInput[tag.id]"
                            class="qualifier-add-input"
                            type="text"
                            :placeholder="(tag.qualifiers && tag.qualifiers.length) ? '新增补充项…' : '添加补充项…'"
                            @keyup.enter="addQualifier(tag, newQualifierInput[tag.id])"
                          />
                          <button
                            class="qualifier-add-btn"
                            type="button"
                            title="新建补充项"
                            @click="addQualifier(tag, newQualifierInput[tag.id])"
                          >+</button>
                        </span>
                      </div>
                    </div>
                    </template>
                  </div>
                </div>
                <div v-else class="no-video-tags">
                  <span>该视频暂无标签</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 推荐视频区域（桌面端位于视频右侧，移动端自动移至下方） -->
    <div class="recommendations-section">
    <div class="recommendations-header">
      <span class="recommendations-title">推荐视频</span>
    </div>
      <div v-if="recommendedLoading" class="recommendations-loading">
        <div class="spinner-small"></div>
        <span>加载中...</span>
      </div>
      <div v-else class="recommendations-list">
        <div
          v-for="rec in recommendedVideos"
          :key="rec.hash"
          class="rec-item"
          @click="handleRecommendationClick(rec)"
        >
          <div class="rec-thumbnail-wrapper">
            <img
              :src="withThumbToken('/thumbnail/' + rec.hash)"
              :alt="(rec.title || rec.file_name || '')"
              class="rec-thumbnail"
              @error="(e:any)=>{ const t=e.target; if(t.dataset.fb) return; t.dataset.fb='1'; t.src='/placeholder.jpg'; }"
            />
            <span v-if="rec.duration" class="rec-duration">{{ formatDuration(rec.duration) }}</span>
          </div>
          <div class="rec-info">
            <div class="rec-title">{{ rec.title || rec.file_name }}</div>
            <div class="rec-meta">{{ rec.view_count || 0 }}播放</div>
          </div>
        </div>
      </div>
    </div>

      <!-- 删除确认对话框 -->
      <div v-if="showDeleteConfirm" class="dialog-overlay" data-testid="delete-confirm-dialog">
        <div class="dialog">
          <h3>确认删除</h3>
          <p>确定要将视频 "{{ video.title }}" 移入回收站吗？管理员可在回收站中恢复或彻底删除。</p>
          <div class="dialog-checkbox">
            <label>
              <input type="checkbox" v-model="deleteFileOption" />
              永久删除（不可恢复，将同时删除文件）
            </label>
          </div>
          <div class="dialog-actions">
            <button class="btn-secondary" @click="showDeleteConfirm = false">取消</button>
            <button class="btn-danger" @click="handleDelete" data-testid="confirm-delete-button">删除</button>
          </div>
        </div>
      </div>

      <!-- 共享观看对话框 -->
      <div v-if="showShareDialog" class="dialog-overlay" data-testid="share-watch-dialog">
        <div class="dialog share-dialog">
          <h3>共享观看</h3>
          <div class="share-info">
            <p class="share-label">分享链接：</p>
            <div class="share-url-box">
              <input 
                type="text" 
                :value="shareUrl" 
                readonly 
                class="share-url-input"
                data-testid="share-url-input"
              />
              <button 
                class="btn-copy" 
                @click="copyShareUrl"
                data-testid="copy-share-url-button"
              >
                复制
              </button>
            </div>
            <p class="share-hint">将此链接分享给好友，即可一起观看视频，播放进度将自动同步</p>
            <div v-if="sharedSession" class="share-status">
              <p class="status-item">
                <span class="status-label">状态：</span>
                <span :class="['status-value', sharedSession.status]">
                  {{ sharedSession.status === 'pending' ? '等待加入' : '观看中' }}
                </span>
              </p>
              <p class="status-item" v-if="sharedSession.invitee_id">
                <span class="status-label">已加入用户</span>
              </p>
            </div>
          </div>
          <div class="dialog-actions">
            <button 
              v-if="isCreator" 
              class="btn-danger" 
              @click="endSharedWatchSession(); showShareDialog = false"
              data-testid="end-share-button"
            >
              结束共享
            </button>
            <button class="btn-secondary" @click="showShareDialog = false">关闭</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 视频不存在 -->
    <div v-else class="error-container">
      <p>视频不存在或已被删除</p>
      <button @click="goBack" class="back-link">返回首页</button>
    </div>

    <!-- 编辑视频抽屉（标题/简介/优先级/资源库/标签） -->
    <ItemEditDrawer
      :visible="editDrawerVisible"
      type="video"
      :item="editingItem"
      @update:visible="editDrawerVisible = $event"
      @saved="onEditSaved"
    />

    <!-- Toast 提示 -->
    <div v-if="showToastFlag" class="toast" data-testid="favorite-success">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.video-page {
  min-height: 100vh;
  background: var(--bg-surface);
  color: var(--text-primary);
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 24px;
  background: transparent;
  border: none;
  color: var(--text-primary);
  font-size: 16px;
  cursor: pointer;
  transition: color 0.2s;
}

.back-btn:hover {
  color: var(--accent);
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 3px solid var(--border-default);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.video-content {
  max-width: 2000px;
  margin: 0 auto;
  padding: 0 24px 40px;
  display: flex;
  gap: 24px;
  align-items: flex-start;
  box-sizing: border-box;
}

.video-main {
  flex: 1 1 0;
  min-width: 0;
}

/* 推荐视频区域 */
.recommendations-section {
  width: 350px;
  flex-shrink: 0;
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 16px;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  position: static;
  top: auto;
  align-self: flex-start;
}

.recommendations-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.recommendations-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}

.recommendations-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--text-secondary);
  font-size: 13px;
}

.spinner-small {
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-default);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

/* 移动端手势层与快进/快退反馈 */
.gesture-layer {
  position: absolute;
  inset: 0;
  z-index: 5;
  touch-action: none;
}

.seek-feedback {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  background: rgba(0, 0, 0, 0.7);
  color: var(--text-on-accent);
  padding: 8px 16px;
  border-radius: 6px;
  font-size: 16px;
  z-index: 6;
  pointer-events: none;
  white-space: nowrap;
}

/* 移动端进度条（替代被关闭的原生控件） */
.mp-bar {
  position: relative;
  height: 16px;
  display: flex;
  align-items: center;
  cursor: pointer;
  touch-action: none;
}

.mp-bar::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  height: 4px;
  border-radius: 2px;
  background: rgba(255, 255, 255, 0.3);
}

.mp-played {
  position: absolute;
  left: 0;
  height: 4px;
  border-radius: 2px;
  background: var(--accent, #3b82f6);
  pointer-events: none;
}

.mp-thumb {
  position: absolute;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #fff;
  transform: translateX(-50%);
  box-shadow: 0 0 4px rgba(0, 0, 0, 0.4);
  pointer-events: none;
}

/* 移动端底部控制栏（播放/暂停 + 进度条 + 全屏） */
.mobile-controls {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  z-index: 7;
  padding: 22px 12px 12px;
  background: linear-gradient(to top, rgba(0, 0, 0, 0.7), rgba(0, 0, 0, 0));
  transition: opacity 0.3s ease;
}

.mc-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
}

.mc-btn {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border: none;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}

.mc-btn:active {
  background: rgba(255, 255, 255, 0.3);
}

.mp-time {
  flex: 1;
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #fff;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}

/* 控制栏自动隐藏 */
.mobile-controls.hidden {
  opacity: 0;
  pointer-events: none;
}

/* 缓冲转圈 + 网速（桌面/移动通用） */
.buffering-overlay {
  position: absolute;
  inset: 0;
  z-index: 8;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: rgba(0, 0, 0, 0.25);
  pointer-events: none;
}

.buffering-spinner {
  width: 44px;
  height: 44px;
  border: 4px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.buffering-speed {
  font-size: 14px;
  color: #fff;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.6);
}

.recommendations-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.rec-item {
  display: flex;
  gap: 10px;
  cursor: pointer;
  border-radius: 8px;
  transition: background 0.2s;
  padding: 4px;
}

.rec-item:hover {
  background: var(--bg-surface-hover);
}

.rec-thumbnail-wrapper {
  position: relative;
  width: 120px;
  height: 68px;
  flex-shrink: 0;
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-surface-2);
}

.rec-thumbnail {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.rec-duration {
  position: absolute;
  bottom: 4px;
  right: 4px;
  background: rgba(0, 0, 0, 0.75);
  color: var(--text-on-accent);
  font-size: 11px;
  padding: 2px 4px;
  border-radius: 3px;
}

.rec-info {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 4px;
}

.rec-title {
  font-size: 13px;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rec-meta {
  font-size: 12px;
  color: var(--text-secondary);
}

.player-section {
  background: #000;
  border-radius: 12px;
  overflow: hidden;
  margin-bottom: 24px;
}

.collection-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  background: var(--accent-soft);
  border: 1px solid var(--info-soft);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 16px;
}
.cn-info { display: flex; align-items: center; gap: 10px; min-width: 0; }
.cn-label { font-size: 12px; color: var(--text-secondary); background: var(--accent-soft); padding: 2px 8px; border-radius: 4px; }
.cn-name { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 280px; }
.cn-progress { font-size: 12px; color: var(--text-secondary); }
.cn-actions { display: flex; align-items: center; gap: 8px; }
.cn-btn {
  background: var(--accent-soft);
  border: none;
  color: var(--text-on-accent);
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
}
.cn-btn:hover:not(:disabled) { background: var(--accent-hover); }
.cn-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.cn-btn.primary { background: var(--accent); }
.cn-btn.primary:hover:not(:disabled) { background: var(--accent-active); }

.video-player-container {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
  isolation: isolate;
  z-index: 1;
}

/* PC 端竖屏全屏入口按钮 */
.portrait-entry-pc {
  position: absolute;
  top: 12px;
  right: 12px;
  z-index: 10;
  width: 38px;
  height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  cursor: pointer;
  backdrop-filter: blur(8px);
  transition: background 0.2s;
}
.portrait-entry-pc:hover {
  background: rgba(0, 0, 0, 0.75);
}

/* 全屏时铺满整个屏幕 */
.video-player-container:fullscreen {
  width: 100vw;
  height: 100vh;
  aspect-ratio: auto;
}

/* ===== 竖屏全屏短视频模式（抖音式沉浸）===== */
.portrait-mode {
  position: fixed;
  inset: 0;
  width: 100vw;
  height: 100vh;
  height: 100dvh;
  background: #000;
  z-index: 2000;
  overflow: hidden;
  touch-action: none;
  overscroll-behavior: contain;
}
/* 纵向 feed 轨道：三格（prev/current/next），每格一个视口高 */
.portrait-track {
  position: absolute;
  left: 0;
  top: 0;
  width: 100%;
  height: 300%;
  will-change: transform;
}
.portrait-track.animating {
  transition: transform 0.28s cubic-bezier(0.22, 0.61, 0.36, 1);
}
.portrait-item {
  position: relative;
  width: 100%;
  height: 33.3333%;
  overflow: hidden;
  background: #000;
}
.portrait-video {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #000;
}
/* 相邻视频预览层 */
.portrait-item-cover {
  width: 100%;
  height: 100%;
  background-size: cover;
  background-position: center;
  filter: brightness(0.7);
}
.portrait-item-ph {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #0a0a0a;
}
.portrait-item-title {
  position: absolute;
  left: 16px;
  right: 80px;
  bottom: 24px;
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.9);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 双击爱心动画 */
.portrait-heart {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 5;
  pointer-events: none;
  filter: drop-shadow(0 2px 8px rgba(0, 0, 0, 0.5));
}
.heart-pop-enter-active {
  animation: heart-pop 0.7s ease-out;
}
@keyframes heart-pop {
  0% { transform: translate(-50%, -50%) scale(0.3); opacity: 0; }
  30% { transform: translate(-50%, -50%) scale(1.2); opacity: 1; }
  70% { transform: translate(-50%, -50%) scale(1); opacity: 1; }
  100% { transform: translate(-50%, -50%) scale(1.4); opacity: 0; }
}
/* 右上角操作按钮 */
.portrait-top {
  position: absolute;
  top: max(12px, env(safe-area-inset-top));
  right: 12px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
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
.portrait-top-btn:active {
  background: rgba(0, 0, 0, 0.7);
}
/* 右侧竖排操作栏 */
.portrait-actions {
  position: absolute;
  right: 14px;
  bottom: 110px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  gap: 20px;
  align-items: center;
}
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
  width: 48px;
  height: 48px;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(4px);
  filter: drop-shadow(0 1px 3px rgba(0, 0, 0, 0.6));
  transition: transform 0.15s, background 0.2s;
}
.portrait-action:active .portrait-action-icon {
  transform: scale(0.9);
}
.portrait-action.active .portrait-action-icon {
  background: rgba(0, 0, 0, 0.55);
}
.portrait-action.active {
  color: #ff2d55;
}
.portrait-action:nth-child(2).active {
  color: #ffd60a;
}
.portrait-action-count {
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
}
/* 左上角不喜欢 */
.portrait-dislike-top {
  position: absolute;
  top: max(12px, env(safe-area-inset-top));
  left: 12px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 7px 12px;
  border-radius: 20px;
  border: none;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  backdrop-filter: blur(4px);
}
.portrait-dislike-top.active {
  color: #ff2d55;
  background: rgba(0, 0, 0, 0.6);
}
/* 底部视频信息 */
.portrait-info {
  position: absolute;
  left: 12px;
  right: 80px;
  bottom: max(20px, env(safe-area-inset-bottom));
  z-index: 9;
  color: #fff;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
  pointer-events: none;
}
.portrait-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.portrait-meta {
  font-size: 12px;
  opacity: 0.7;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* 加载指示 */
.portrait-loading {
  position: absolute;
  inset: 0;
  z-index: 8;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}
.buffering-spinner {
  width: 36px;
  height: 36px;
  border: 3px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

.video-element {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

/* 精彩片段标记进度条 */
.marker-track {
  position: absolute;
  top: 8px;
  left: 8px;
  right: 8px;
  height: 6px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 3px;
  z-index: 3;
  pointer-events: auto;
}

.marker-tick {
  position: absolute;
  top: 50%;
  width: 10px;
  height: 10px;
  margin-left: -5px;
  transform: translateY(-50%);
  background: #ff4d6d;
  border: 2px solid var(--text-primary);
  border-radius: 50%;
  cursor: pointer;
  transition: transform 0.15s;
}

.marker-tick:hover {
  transform: translateY(-50%) scale(1.4);
}

.marker-tip {
  position: absolute;
  bottom: 18px;
  left: 50%;
  transform: translateX(-50%);
  white-space: nowrap;
  background: #000;
  color: var(--text-on-accent);
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 6px;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.15s;
}

.marker-tick:hover .marker-tip {
  opacity: 1;
}

.auto-continue-overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.55);
  z-index: 5;
}

.ac-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 24px 28px;
  text-align: center;
  min-width: 240px;
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.5);
}

.ac-title {
  color: var(--text-secondary);
  font-size: 13px;
  margin-bottom: 6px;
}

.ac-name {
  color: var(--text-primary);
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 10px;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ac-count {
  color: var(--text-secondary);
  font-size: 13px;
  margin-bottom: 16px;
}

.ac-actions {
  display: flex;
  gap: 10px;
  justify-content: center;
}

.ac-btn {
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.ac-cancel {
  background: var(--bg-surface-2);
  color: var(--text-secondary);
}

.ac-cancel:hover {
  background: var(--border-strong);
}

.ac-now {
  background: #ff4d6d;
  color: var(--text-primary);
  font-weight: 600;
}

.ac-now:hover {
  background: #ff3a5c;
}

.video-info-section {
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 24px;
}

.video-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0;
  color: var(--text-primary);
}

.video-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

/* 标题右侧操作区：编辑按钮 + “更多”菜单，整体靠右对齐 */
.title-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* 标题旁的“编辑”按钮（管理员）已收纳至底部“更多”菜单 */


/* “更多”菜单（收纳不常用操作：显示/隐藏） */
.more-menu-wrap { position: relative; flex-shrink: 0; }
.more-menu-btn { padding: 7px 10px; }
.more-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 200px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.45);
  padding: 6px;
  z-index: 50;
}
.more-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  font-size: 13px;
  padding: 9px 10px;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s;
}
.more-menu-item:hover { background: var(--bg-surface-hover); color: var(--accent); }
.more-menu-item:disabled { opacity: 0.5; cursor: not-allowed; }


.video-meta {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  color: var(--text-tertiary);
  font-size: 14px;
}

.video-description {
  font-size: 15px;
  line-height: 1.6;
  color: var(--text-secondary);
  margin-bottom: 16px;
  white-space: pre-wrap;
}

.video-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}

.tag-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: var(--bg-surface-2);
  border-radius: 16px;
  font-size: 13px;
  color: var(--text-secondary);
}

/* 标签编辑工具条（管理员编辑模式开关） */
.tag-edit-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.edit-mode-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: 8px;
  border: 1px solid var(--border-strong);
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.edit-mode-toggle:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.edit-mode-toggle.active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--text-on-accent);
}

.edit-mode-hint {
  font-size: 12px;
  color: var(--text-secondary);
}

/* 管理员可编辑的标签：高亮边框提示 */
.tag-badge.admin-editable {
  border: 1px solid transparent;
}

/* 标签删除/重命名标记：克制的幽灵样式，仅在编辑模式出现 */
.tag-remove-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: #f87171;
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0.6;
  transition: all 0.15s;
}

.tag-remove-btn:hover {
  background: rgba(248, 113, 113, 0.18);
  opacity: 1;
}

/* 重命名铅笔标记 */
.tag-edit-pencil {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: none;
  background: transparent;
  color: #60a5fa;
  cursor: pointer;
  flex-shrink: 0;
  opacity: 0.6;
  transition: all 0.15s;
}

.tag-edit-pencil:hover {
  background: rgba(96, 165, 250, 0.18);
  opacity: 1;
}

/* 交互按钮栏 */
.interaction-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 16px;
  padding: 20px 0;
  border-top: 1px solid var(--border-default);
  border-bottom: 1px solid var(--border-default);
  margin: 20px 0;
}

/* 左侧交互按钮组 */
.interaction-buttons {
  display: flex;
  gap: 8px;
}

.interact-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.interact-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-secondary);
  transform: scale(1.05);
}

.interact-btn .btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: transparent;
  transition: all 0.2s ease;
}

.interact-btn:hover .btn-icon {
  background: rgba(255, 255, 255, 0.1);
}

.interact-btn .btn-label {
  display: block;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.2;
}

/* 点赞按钮 */
.interact-btn.like-btn:hover,
.interact-btn.like-btn.active {
  color: var(--danger);
}

.interact-btn.like-btn:hover .btn-icon,
.interact-btn.like-btn.active .btn-icon {
  background: rgba(255, 107, 107, 0.15);
}

.interact-btn.like-btn.active .btn-icon {
  animation: likeAnim 0.3s ease;
}

@keyframes likeAnim {
  0% { transform: scale(1); }
  50% { transform: scale(1.3); }
  100% { transform: scale(1); }
}

/* 踩按钮 */
.interact-btn.dislike-btn:hover,
.interact-btn.dislike-btn.active {
  color: #ffd93d;
}

.interact-btn.dislike-btn:hover .btn-icon,
.interact-btn.dislike-btn.active .btn-icon {
  background: rgba(255, 217, 61, 0.15);
}

/* 收藏按钮 */
.interact-btn.favorite-btn:hover,
.interact-btn.favorite-btn.active {
  color: #ff6b9d;
}

.interact-btn.favorite-btn:hover .btn-icon,
.interact-btn.favorite-btn.active .btn-icon {
  background: rgba(255, 107, 157, 0.15);
}

.interact-btn.favorite-btn.active .btn-icon {
  animation: favoriteAnim 0.4s ease;
}

@keyframes favoriteAnim {
  0% { transform: scale(1); }
  25% { transform: scale(1.2); }
  50% { transform: scale(0.95); }
  75% { transform: scale(1.1); }
  100% { transform: scale(1); }
}

/* 稍后看按钮 */
.interact-btn.watchlater-btn:hover,
.interact-btn.watchlater-btn.active {
  color: #69dbff;
}

/* 继续观看按钮 */
.interact-btn.continuewatch-btn:hover,
.interact-btn.continuewatch-btn.active {
  color: #ffa94d;
}

.interact-btn.watchlater-btn:hover .btn-icon,
.interact-btn.watchlater-btn.active .btn-icon {
  background: rgba(105, 219, 255, 0.15);
}

.interact-btn.watchlater-btn.active .btn-icon svg polyline {
  stroke: #69dbff;
}

/* 共享观看按钮 */
.interact-btn.sharewatch-btn:hover,
.interact-btn.sharewatch-btn.active {
  color: var(--accent);
}

.interact-btn.sharewatch-btn:hover .btn-icon,
.interact-btn.sharewatch-btn.active .btn-icon {
  background: var(--accent-soft);
}

/* 右侧操作按钮 */
.action-buttons {
  display: flex;
  gap: 4px;
}

.action-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 8px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: var(--text-secondary);
  transform: scale(1.05);
}

.action-btn.active {
  color: var(--accent);
}

.action-btn.active:hover {
  color: var(--accent);
}

.action-btn .btn-label {
  display: block;
  font-size: 11px;
  color: var(--text-secondary);
  line-height: 1.2;
}

/* 合集作为分类归属展示 */
.collection-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.collection-meta:hover {
  background: var(--accent-soft-hover);
}

/* 更多菜单 */
.more-wrap {
  position: relative;
}

.more-menu {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 140px;
  background: var(--bg-surface);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 10px;
  padding: 6px;
  z-index: 50;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.more-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 8px 10px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.more-item:hover {
  background: rgba(255, 255, 255, 0.08);
}

.more-item.active {
  color: #ff7043;
}

.more-item.collection-item {
  padding: 4px 6px;
  cursor: default;
}

.more-item.collection-item:hover {
  background: transparent;
}

.error-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  color: var(--text-tertiary);
}

.back-link {
  margin-top: 16px;
  padding: 10px 24px;
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: var(--text-on-accent);
  font-size: 14px;
  cursor: pointer;
}

/* 编辑表单 */
.edit-form {
  background: var(--bg-surface-hover);
  border-radius: 12px;
  padding: 24px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-size: 14px;
  color: var(--text-tertiary);
  margin-bottom: 8px;
}

/* 标签输入框包装器 */
.tag-input-wrapper {
  position: relative;
}

.tag-input-wrapper input {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  font-size: 14px;
  box-sizing: border-box;
}

.tag-input-wrapper input:focus {
  outline: none;
  border-color: var(--accent);
}

/* 标签智能建议下拉框 */
.tag-suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-strong);
  border-top: none;
  border-radius: 0 0 8px 8px;
  max-height: 200px;
  overflow-y: auto;
  z-index: 10001;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.tag-suggestion-item {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-default);
  transition: background 0.2s;
}

.tag-suggestion-item:last-child {
  border-bottom: none;
}

.tag-suggestion-item:hover {
  background: var(--bg-surface-hover);
}

.suggestion-path {
  color: var(--text-primary);
  font-size: 14px;
}

/* 标签区域 */
.video-tags-section {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}

.video-tags-section .video-tags {
  margin-bottom: 0;
}

.tag-add-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: var(--bg-surface-2);
  border: 1px dashed var(--border-strong);
  border-radius: 50%;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.tag-add-btn:hover {
  background: var(--border-strong);
  border-color: var(--text-tertiary);
  color: var(--accent);
}

/* 标签编辑器对话框 */
.tag-editor-dialog {
  width: 90vw;
  max-width: 1200px;
  min-width: 600px;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

/* 大屏幕（>1400px）更宽 */
@media (min-width: 1400px) {
  .tag-editor-dialog {
    width: 85vw;
    max-width: 1400px;
  }
}

/* 中等屏幕（1024px-1400px） */
@media (min-width: 1024px) and (max-width: 1399px) {
  .tag-editor-dialog {
    width: 90vw;
    max-width: 1100px;
  }
}

/* 小屏幕（768px-1024px） */
@media (min-width: 768px) and (max-width: 1023px) {
  .tag-editor-dialog {
    width: 95vw;
    max-width: 900px;
    min-width: 500px;
  }
}

.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-default);
  flex-shrink: 0;
}

.dialog-header h3 {
  margin: 0;
  font-size: 18px;
}

.close-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  font-size: 24px;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.close-btn:hover {
  color: var(--accent);
}

/* 标签编辑器主体：左右分栏 */
.tag-editor-body {
  display: flex;
  gap: 16px;
  flex: 1;
  min-height: 0;
  margin-top: 16px;
}

/* 左侧标签树面板 */
.tag-tree-panel {
  width: 180px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border-default);
  padding-right: 16px;
}

.panel-title {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 12px;
  flex-shrink: 0;
}

.tag-tree-container {
  flex: 1;
  overflow-y: auto;
  min-height: 100px;
}

.tag-tree-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 4px;
}

.tag-tree-item:hover {
  background: var(--bg-surface-hover);
}

.tag-tree-item.active {
  background: var(--accent);
}

.tag-tree-name {
  flex: 1;
  font-size: 14px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-tree-item.active .tag-tree-name {
  color: var(--text-primary);
}

.tag-tree-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-tertiary);
  background: var(--bg-surface-2);
  padding: 2px 8px;
  border-radius: 10px;
  flex-shrink: 0;
}

.tag-tree-arrow {
  font-size: 14px;
  font-weight: bold;
}

.tag-tree-leaf {
  font-size: 12px;
  color: #4CAF50;
  flex-shrink: 0;
}

/* 面包屑导航 */
.tag-breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 10px;
  background: var(--bg-surface);
  border-radius: 6px;
  margin-bottom: 10px;
  font-size: 13px;
  flex-shrink: 0;
  overflow: hidden;
}

.breadcrumb-root {
  color: #4FC3F7;
  cursor: pointer;
  flex-shrink: 0;
}

.breadcrumb-root:hover {
  text-decoration: underline;
}

.breadcrumb-sep {
  color: var(--border-strong);
  flex-shrink: 0;
}

.breadcrumb-item {
  color: var(--text-secondary);
  cursor: pointer;
  flex-shrink: 0;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.breadcrumb-item:hover {
  color: var(--accent);
}

.breadcrumb-item.active {
  color: #4FC3F7;
  cursor: default;
}

.breadcrumb-back {
  margin-left: auto;
  background: var(--bg-surface-2);
  border: none;
  color: var(--text-secondary);
  font-size: 18px;
  width: 24px;
  height: 24px;
  border-radius: 4px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.breadcrumb-back:hover {
  background: var(--border-strong);
  color: var(--accent);
}

/* 右侧输入面板 */
.tag-input-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

/* 当前路径显示 */
.current-path-display {
  padding: 10px 12px;
  background: var(--bg-surface);
  border-radius: 8px;
  font-size: 13px;
  flex-shrink: 0;
}

.path-label {
  color: var(--text-tertiary);
}

.path-value {
  color: var(--text-primary);
}

.path-part {
  color: #4FC3F7;
}

.path-separator {
  color: var(--text-secondary);
  margin: 0 2px;
}

.path-placeholder {
  color: var(--border-strong);
}

/* 输入框包装 */
.tag-input-wrapper {
  display: flex;
  gap: 8px;
  position: relative;
  flex-shrink: 0;
}

.tag-input-wrapper .tag-input {
  flex: 1;
}

.slash-btn {
  width: 36px;
  height: 40px;
  background: var(--bg-surface-2);
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 18px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.slash-btn:hover {
  background: var(--border-strong);
  border-color: var(--text-tertiary);
  color: var(--accent);
}

/* 输入区域操作按钮 */
.tag-input-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  flex-shrink: 0;
}

/* 视频标签列表 */
.video-tags-list {
  border-top: 1px solid var(--border-default);
  padding-top: 12px;
  flex-shrink: 0;
  max-height: 200px;
  overflow-y: auto;
}

.video-tags-list-header {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 10px;
}

/* 当前标签列表 */
.current-tags {
  margin-bottom: 20px;
}

.tag-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  background: var(--bg-surface-hover);
  border-radius: 8px;
  margin-bottom: 8px;
}

.tag-item .tag-name {
  flex: 1;
  color: var(--text-secondary);
  font-size: 14px;
}

.tag-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.tag-item:hover .tag-actions {
  opacity: 1;
}

.tag-edit-row {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  position: relative;
}

.tag-edit-input {
  flex: 1;
  padding: 8px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 14px;
}

.tag-edit-input:focus {
  outline: none;
  border-color: var(--accent);
}

.no-tags {
  color: var(--text-tertiary);
  text-align: center;
  padding: 20px;
  font-size: 14px;
}

/* 过滤状态提示 */
.filter-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--bg-surface);
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--text-secondary);
}

.clear-filter {
  background: none;
  border: 1px solid var(--border-strong);
  color: var(--text-secondary);
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.clear-filter:hover {
  background: var(--bg-surface-2);
  color: var(--accent);
  border-color: var(--border-strong);
}

/* 扁平标签列表（过滤状态） */
.tag-flat-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
  margin-bottom: 4px;
  border: 1px solid transparent;
}

.tag-flat-item:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-strong);
}

.tag-flat-item.active {
  background: var(--accent);
  border-color: #1976D2;
}

.tag-flat-path {
  font-size: 14px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.tag-flat-item:hover .tag-flat-path {
  color: var(--accent);
}

.tag-flat-item.active .tag-flat-path {
  color: var(--text-primary);
}

.tag-flat-check {
  font-size: 12px;
  color: #4CAF50;
  margin-left: 8px;
  flex-shrink: 0;
}

.tag-flat-item.active .tag-flat-check {
  color: var(--text-primary);
}

/* 添加标签区域 */
.add-tag-section {
  padding-top: 16px;
  border-top: 1px solid var(--border-default);
  position: relative;
}

.tag-input-row {
  display: flex;
  gap: 8px;
}

.tag-input {
  flex: 1;
  padding: 10px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
}

.tag-input:focus {
  outline: none;
  border-color: var(--accent);
}

.tag-hint {
  margin-top: 12px;
  font-size: 12px;
  color: var(--text-tertiary);
}

/* 标签编辑器中的通用按钮样式 */
.tag-editor-dialog .btn-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: transparent;
  border: none;
  border-radius: 4px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
}

.tag-editor-dialog .btn-icon:hover {
  background: var(--accent-soft);
  color: var(--accent);
}

.tag-editor-dialog .btn-primary {
  padding: 8px 16px;
  background: var(--accent);
  border: none;
  border-radius: 6px;
  color: var(--text-on-accent);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.tag-editor-dialog .btn-primary:hover {
  background: var(--accent-active);
}

.form-group input,
.form-group textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 15px;
  box-sizing: border-box;
}

.form-group input:focus,
.form-group textarea:focus {
  outline: none;
  border-color: var(--accent);
}

.form-group textarea {
  resize: vertical;
  min-height: 100px;
}

.form-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.btn-secondary {
  padding: 10px 24px;
  background: transparent;
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-secondary:hover {
  background: var(--bg-surface-2);
}

.btn-primary {
  padding: 10px 24px;
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: var(--text-on-accent);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: var(--accent-active);
}

.btn-danger {
  padding: 10px 24px;
  background: #f44336;
  border: none;
  border-radius: 8px;
  color: var(--text-on-accent);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-danger:hover {
  background: #d32f2f;
}

.edit-btn:hover {
  background: var(--accent);
}

.delete-btn:hover {
  background: #f44336;
}

/* 对话框 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 10000;
}

.dialog {
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 24px;
  width: 90%;
  max-width: 400px;
}

.dialog h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 16px 0;
}

.dialog p {
  color: var(--text-secondary);
  margin: 0 0 12px 0;
}

.warning-text {
  color: #ff9800;
  font-size: 13px;
}

.dialog-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 20px;
}

.dialog-checkbox {
  margin: 16px 0;
  padding: 12px;
  background: var(--bg-surface-hover);
  border-radius: 8px;
}

.dialog-checkbox label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--text-secondary);
  font-size: 14px;
}

.dialog-checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

/* 共享观看对话框 */
.share-dialog {
  max-width: 500px;
}

.share-info {
  margin-bottom: 20px;
}

.share-label {
  font-size: 14px;
  color: var(--text-tertiary);
  margin-bottom: 8px;
}

.share-url-box {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.share-url-input {
  flex: 1;
  padding: 10px 12px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  font-family: monospace;
}

.btn-copy {
  padding: 10px 16px;
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: var(--text-on-accent);
  font-size: 14px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.2s;
}

.btn-copy:hover {
  background: var(--accent-active);
}

.share-hint {
  font-size: 13px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

.share-status {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-default);
}

.status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 14px;
}

.status-label {
  color: var(--text-tertiary);
}

.status-value {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 13px;
}

.status-value.pending {
  background: #ff9800;
  color: var(--text-primary);
}

.status-value.active {
  background: #4caf50;
  color: var(--text-on-accent);
}

/* Toast 提示 */
.toast {
  position: fixed;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.8);
  color: var(--text-on-accent);
  padding: 12px 24px;
  border-radius: 24px;
  font-size: 14px;
  z-index: 2000;
  animation: fadeInOut 2s ease;
}

@keyframes fadeInOut {
  0% { opacity: 0; transform: translateX(-50%) translateY(20px); }
  10% { opacity: 1; transform: translateX(-50%) translateY(0); }
  90% { opacity: 1; transform: translateX(-50%) translateY(0); }
  100% { opacity: 0; transform: translateX(-50%) translateY(-20px); }
}

@media (max-width: 768px) {
  .video-title {
    font-size: 18px;
  }

  /* 交互按钮移动端适配 - 允许换行 */
  .interaction-bar {
    gap: 12px;
    padding: 16px 0;
  }

  .interaction-buttons {
    flex-wrap: wrap;
    gap: 8px;
    justify-content: center;
  }

  .interact-btn {
    padding: 6px 4px;
    flex: 1 1 calc(33% - 4px);
    max-width: calc(33% - 4px);
    min-width: 60px;
  }

  .interact-btn .btn-icon {
    width: 24px;
    height: 24px;
  }

  .interact-btn svg {
    width: 18px;
    height: 18px;
  }

  .interact-btn .btn-label {
    font-size: 10px;
  }

  .action-buttons {
    gap: 4px;
    justify-content: center;
  }

  .action-btn {
    padding: 6px 8px;
    flex: 1 1 calc(50% - 4px);
    max-width: calc(50% - 4px);
  }

  .action-btn svg {
    width: 18px;
    height: 18px;
  }

  .action-btn .btn-label {
    font-size: 10px;
  }

  /* 移动端标签编辑器 - 上下布局，输入区域触手可及 */
  .tag-editor-dialog {
    width: 100vw;
    max-width: 100vw;
    min-width: 0;
    height: 85vh;
    max-height: 85vh;
    margin: 0;
    border-radius: 0;
    z-index: 100001;
    position: fixed;
    top: 0;
    left: 0;
  }

  /* 移动端：对话框打开时隐藏视频，防止 video 元素提升层级覆盖对话框 */
  .video-player-container.hide-on-mobile,
  .video-player-container.hide-on-mobile * {
    display: none !important;
    visibility: hidden !important;
  }

  .tag-editor-body {
    flex-direction: column;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .tag-tree-panel {
    width: 100%;
    border-right: none;
    border-bottom: 1px solid var(--border-default);
    padding-right: 0;
    padding-bottom: 12px;
    max-height: none;
    overflow: visible;
  }

  .tag-tree-container {
    display: block;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    max-height: 45vh;
    min-height: 0;
  }

  .tag-tree-item {
    display: inline-block;
    margin-bottom: 4px;
    background: var(--bg-surface-hover);
    padding: 6px 12px;
  }

  /* 移动端标签建议下拉框适配 */
  .tag-suggestions {
    position: fixed;
    left: 16px;
    right: 16px;
    max-height: 40vh;
    z-index: 100002;
  }

  /* 视频标签列表移动端适配 */
  .video-tags-list {
    max-height: 22vh;
    overflow-y: auto;
  }

  /* 移动端标签编辑区域确保不被遮挡 */
  .tag-input-panel {
    flex-shrink: 0;
    width: 100%;
  }

  /* 移动端视频标签横向换行显示 */
  .video-tags-list .tag-item {
    display: inline-block;
    margin-bottom: 4px;
    margin-right: 4px;
  }

  .tag-breadcrumb {
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .tag-breadcrumb::-webkit-scrollbar {
    display: none;
  }

  .tag-input-panel {
    flex: 1;
    min-height: 0;
  }

  .video-tags-list {
    max-height: 20vh;
  }
}

/* 移动端：推荐视频显示在视频下方 */
@media (max-width: 1024px) {
  .video-content {
    flex-direction: column;
    padding: 0 16px;
  }

  .recommendations-section {
    width: 100%;
    max-height: none;
    position: static;
    margin-top: 16px;
  }

  .recommendations-list {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }

  .rec-item {
    flex-direction: column;
    min-width: 0;
  }

  .rec-thumbnail-wrapper {
    width: 100%;
    height: auto;
    min-width: 0;
    aspect-ratio: 16 / 9;
    overflow: hidden;
  }
}

@media (max-width: 480px) {
  .recommendations-section {
    padding: 12px;
  }

  .recommendations-list {
    grid-template-columns: 1fr;
  }

  .rec-thumbnail-wrapper {
    height: auto;
    min-width: 0;
    aspect-ratio: 16 / 9;
    overflow: hidden;
  }
}
/* 精彩片段标记 */
.markers-section {
  margin: 16px 0;
  padding: 14px 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
}
.markers-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
}
.markers-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
}
.markers-add-btn {
  padding: 6px 12px;
  border: 1px solid var(--accent-border);
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.markers-add-btn:hover:not(:disabled) {
  background: var(--accent);
  color: var(--text-on-accent);
}
.markers-add-btn:disabled {
  opacity: 0.5;
  cursor: default;
}
.marker-form {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.marker-note-input {
  flex: 1;
  height: 36px;
  padding: 0 12px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 14px;
}
.marker-save,
.marker-cancel {
  padding: 0 14px;
  height: 36px;
  border-radius: 8px;
  border: 1px solid var(--border-default);
  background: var(--bg-surface-2);
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
}
.marker-save {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--text-on-accent);
}
.marker-save:hover {
  background: var(--accent-active);
}
.markers-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.marker-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.marker-item:hover {
  background: var(--bg-surface-hover);
  border-color: var(--info-soft);
}
.marker-time {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: var(--text-secondary);
  font-size: 13px;
  white-space: nowrap;
}
.marker-note {
  flex: 1;
  color: var(--text-tertiary);
  font-size: 14px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.marker-del {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
}
.marker-del:hover {
  background: var(--danger-soft);
  color: var(--danger);
}
.markers-empty {
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

@media (max-width: 1024px) {
  .markers-header {
    flex-direction: column;
    align-items: stretch;
  }
}
/* 标签补充项（qualifiers） */
.tag-qualifiers {
  display: inline-flex;
  gap: 4px;
  margin-left: 6px;
  flex-wrap: wrap;
  vertical-align: middle;
}
.tag-qualifiers .q-chip {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.12);
  color: #cbd5e1;
}
.tag-line {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.tag-qualifiers-edit {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 4px;
  width: 100%;
}
.qualifier-chip {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid var(--border-default);
  background: transparent;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
  transition: all 0.15s ease;
}
.qualifier-chip:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.qualifier-chip.on {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
}
.qualifier-add {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.qualifier-add-input {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px dashed var(--border-default);
  background: var(--bg-base);
  color: var(--text-primary);
  width: 110px;
  outline: none;
}
.qualifier-add-input:focus {
  border-color: var(--accent);
  border-style: solid;
}
.qualifier-add-btn {
  font-size: 14px;
  line-height: 1;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  border: 1px solid rgba(105, 219, 255, 0.5);
  background: rgba(105, 219, 255, 0.12);
  color: #69dbff;
  cursor: pointer;
  transition: all 0.15s ease;
}
.qualifier-add-btn:hover {
  background: #69dbff;
  color: var(--bg-surface-2);
}
</style>
