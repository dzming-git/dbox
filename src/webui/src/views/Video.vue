<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import { useUserStore } from '../stores/userStore'
import { tagApi, videoApi, collectionSetApi, resourceApi } from '../api'
import ItemEditDrawer from '../components/ItemEditDrawer.vue'
import CollectionPanel from '../components/CollectionPanel.vue'
import type { Video, Tag, VideoTagRef, VideoMarker } from '../types'
import { withThumbToken } from '../utils/media'

const route = useRoute()
const router = useRouter()
const videoStore = useVideoStore()
const userStore = useUserStore()
const watchLaterStore = useWatchLaterStore()

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

// 精彩片段标记（用户个人时间戳）
const markers = ref<VideoMarker[]>([])
const showMarkerForm = ref(false)
const markerNote = ref('')
const currentTime = ref(0)

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
const onVideoEnded = () => {
  if (nextItem.value) goCollectionItem(nextItem.value)
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
  document.addEventListener('click', onDocClickCloseMenu)
})

function onDocClickCloseMenu(e: Event) {
  if (!moreMenuOpen.value) return
  const wrap = document.querySelector('.more-menu-wrap')
  if (wrap && !wrap.contains(e.target as Node)) moreMenuOpen.value = false
}

// 切换视频（含合集内上一集/下一集）时重新加载
watch(videoHash, async () => {
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

// 换一批推荐
const shuffleRecommendations = async () => {
  await fetchRecommendedVideos()
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

// 保存点赞状态到localStorage
const saveLikeStatus = () => {
  if (!video.value) return
  const likedVideos = JSON.parse(localStorage.getItem('likedVideos') || '[]')
  if (isLiked.value) {
    if (!likedVideos.includes(video.value.hash)) {
      likedVideos.push(video.value.hash)
    }
  } else {
    const index = likedVideos.indexOf(video.value.hash)
    if (index > -1) likedVideos.splice(index, 1)
  }
  localStorage.setItem('likedVideos', JSON.stringify(likedVideos))
}

// 保存收藏状态到localStorage
const saveFavoriteStatus = () => {
  if (!video.value) return
  const favoritedVideos = JSON.parse(localStorage.getItem('favoritedVideos') || '[]')
  const favorites = JSON.parse(localStorage.getItem('favorites') || '[]')
  
  if (isFavorited.value) {
    if (!favoritedVideos.includes(video.value.hash)) {
      favoritedVideos.push(video.value.hash)
    }
    // 添加到收藏列表
    if (!favorites.find((f: any) => f.hash === video.value!.hash)) {
      favorites.push({
        hash: video.value.hash,
        title: video.value.title,
        thumbnail: video.value.thumbnail,
        duration: video.value.duration,
        favorited_at: new Date().toISOString()
      })
    }
  } else {
    const index = favoritedVideos.indexOf(video.value.hash)
    if (index > -1) favoritedVideos.splice(index, 1)
    // 从收藏列表移除
    const favIndex = favorites.findIndex((f: any) => f.hash === video.value!.hash)
    if (favIndex > -1) favorites.splice(favIndex, 1)
  }
  
  localStorage.setItem('favoritedVideos', JSON.stringify(favoritedVideos))
  localStorage.setItem('favorites', JSON.stringify(favorites))
}

// 保存踩状态到localStorage
const saveDislikeStatus = () => {
  if (!video.value) return
  const dislikedVideos = JSON.parse(localStorage.getItem('dislikedVideos') || '[]')
  if (isDisliked.value) {
    if (!dislikedVideos.includes(video.value.hash)) {
      dislikedVideos.push(video.value.hash)
    }
  } else {
    const index = dislikedVideos.indexOf(video.value.hash)
    if (index > -1) dislikedVideos.splice(index, 1)
  }
  localStorage.setItem('dislikedVideos', JSON.stringify(dislikedVideos))
}

// 添加到观看历史
const addToHistory = () => {
  if (!video.value) return
  const history = JSON.parse(localStorage.getItem('watchHistory') || '[]')
  const existingIndex = history.findIndex((h: any) => h.hash === video.value!.hash)
  
  const historyItem = {
    hash: video.value.hash,
    title: video.value.title,
    thumbnail: video.value.thumbnail,
    duration: video.value.duration,
    progress: 0,
    watched_at: new Date().toISOString()
  }
  
  if (existingIndex > -1) {
    history.splice(existingIndex, 1)
  }
  history.unshift(historyItem)
  
  // 限制历史记录数量
  if (history.length > 100) history.pop()
  
  localStorage.setItem('watchHistory', JSON.stringify(history))
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
    saveLikeStatus()
  }
}

const handleFavorite = async () => {
  if (!video.value) return
  const response = await videoStore.favoriteVideo(video.value.hash) as any
  if (response && response.favorite_count !== undefined) {
    video.value.favorite_count = response.favorite_count
    isFavorited.value = response.favorited
    saveFavoriteStatus()
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
  saveDislikeStatus()
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
  // 共享模式下立即同步播放状态
  if (isSharedMode.value && shareCode.value && videoPlayer.value) {
    lastSyncedPlaying.value = true
    lastSyncedTime.value = videoPlayer.value.currentTime
    syncPlaybackState(true)
  }
}

const onPause = () => {
  isPlaying.value = false
  // 共享模式下立即同步播放状态
  if (isSharedMode.value && shareCode.value && videoPlayer.value) {
    lastSyncedPlaying.value = false
    lastSyncedTime.value = videoPlayer.value.currentTime
    syncPlaybackState(true)
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
  document.removeEventListener('click', onDocClickCloseMenu)
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

const jumpToMarker = (time: number) => {
  const player = videoPlayer.value
  if (player) {
    player.currentTime = time
    player.play().catch(() => {})
  }
}

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

const onTimeUpdate = () => {
  if (videoPlayer.value) currentTime.value = videoPlayer.value.currentTime
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
              @ended="onVideoEnded"
              preload="metadata"
              controls
            ></video>
          </div>
        </div>

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
            <button
              v-if="canManageVideo"
              class="edit-video-btn"
              @click="openEditDrawer"
              title="编辑视频信息"
              data-testid="edit-video-button"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
              编辑
            </button>
            <div v-if="isAdmin" class="more-menu-wrap">
              <button
                class="edit-video-btn more-menu-btn"
                @click="moreMenuOpen = !moreMenuOpen"
                title="更多操作"
                :aria-expanded="moreMenuOpen"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="none">
                  <circle cx="5" cy="12" r="1.6"/>
                  <circle cx="12" cy="12" r="1.6"/>
                  <circle cx="19" cy="12" r="1.6"/>
                </svg>
              </button>
              <div v-if="moreMenuOpen" class="more-menu" @click="moreMenuOpen = false">
                <button
                  class="more-menu-item"
                  @click="toggleHidden"
                  :disabled="togglingHidden"
                  data-testid="toggle-hidden-button"
                >
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/>
                    <line x1="1" y1="1" x2="23" y2="23"/>
                  </svg>
                  {{ isHidden ? '显示资源（在视频库可见）' : '隐藏资源（仅帖子流可见）' }}
                </button>
              </div>
            </div>
          </div>
        </div>

        <div class="video-meta">
          <span class="meta-item" data-testid="view-count">{{ video.view_count }} 次观看</span>
          <span class="meta-item">{{ formatDuration(video.duration || 0) }}</span>
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
        <button class="shuffle-btn" @click="shuffleRecommendations" :disabled="recommendedLoading">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M23 4v6h-6M1 20v-6h6"/>
            <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>
          </svg>
          换一批
        </button>
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
              @error="($event.target as HTMLImageElement).src = '/placeholder.jpg'"
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
  background: #0f0f0f;
  color: #fff;
}

.back-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px 24px;
  background: transparent;
  border: none;
  color: #fff;
  font-size: 16px;
  cursor: pointer;
  transition: color 0.2s;
}

.back-btn:hover {
  color: #2196F3;
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
  border: 3px solid #333;
  border-top-color: #2196F3;
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
  background: #181818;
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
  color: #fff;
}

.shuffle-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  background: #252525;
  border: 1px solid #333;
  border-radius: 6px;
  color: #aaa;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.shuffle-btn:hover:not(:disabled) {
  background: #333;
  color: #fff;
}

.shuffle-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.recommendations-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: #888;
  font-size: 13px;
}

.spinner-small {
  width: 16px;
  height: 16px;
  border: 2px solid #333;
  border-top-color: #2196F3;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
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
  background: #252525;
}

.rec-thumbnail-wrapper {
  position: relative;
  width: 120px;
  height: 68px;
  flex-shrink: 0;
  border-radius: 6px;
  overflow: hidden;
  background: #333;
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
  color: #fff;
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
  color: #fff;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.rec-meta {
  font-size: 12px;
  color: #888;
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
  background: #1e2740;
  border: 1px solid #2c3a5e;
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 16px;
}
.cn-info { display: flex; align-items: center; gap: 10px; min-width: 0; }
.cn-label { font-size: 12px; color: #9db4e0; background: #2c3a5e; padding: 2px 8px; border-radius: 4px; }
.cn-name { font-weight: 600; font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 280px; }
.cn-progress { font-size: 12px; color: #9db4e0; }
.cn-actions { display: flex; align-items: center; gap: 8px; }
.cn-btn {
  background: #2c3a5e;
  border: none;
  color: #fff;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
}
.cn-btn:hover:not(:disabled) { background: #38507f; }
.cn-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.cn-btn.primary { background: #2196F3; }
.cn-btn.primary:hover:not(:disabled) { background: #1976D2; }

.video-player-container {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
  isolation: isolate;
  z-index: 1;
}

.video-element {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.video-info-section {
  background: #1a1a1a;
  border-radius: 12px;
  padding: 24px;
}

.video-title {
  font-size: 24px;
  font-weight: 600;
  margin: 0;
  color: #fff;
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

/* 标题旁的“编辑”按钮（管理员） */
.edit-video-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
  padding: 7px 14px;
  border-radius: 8px;
  border: 1px solid #444;
  background: #252525;
  color: #ddd;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.edit-video-btn:hover {
  border-color: #2196F3;
  color: #fff;
  background: #2d2d2d;
}

/* “更多”菜单（收纳不常用操作：显示/隐藏） */
.more-menu-wrap { position: relative; flex-shrink: 0; }
.more-menu-btn { padding: 7px 10px; }
.more-menu {
  position: absolute;
  top: calc(100% + 6px);
  right: 0;
  min-width: 200px;
  background: #1f1f1f;
  border: 1px solid #3a3a3a;
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
  color: #ddd;
  font-size: 13px;
  padding: 9px 10px;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.15s;
}
.more-menu-item:hover { background: #2d2d2d; color: #fff; }
.more-menu-item:disabled { opacity: 0.5; cursor: not-allowed; }


.video-meta {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  color: #999;
  font-size: 14px;
}

.video-description {
  font-size: 15px;
  line-height: 1.6;
  color: #ccc;
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
  background: #333;
  border-radius: 16px;
  font-size: 13px;
  color: #ccc;
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
  border: 1px solid #444;
  background: #1a1a1a;
  color: #ccc;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.edit-mode-toggle:hover {
  border-color: #2196F3;
  color: #fff;
}

.edit-mode-toggle.active {
  background: #2196F3;
  border-color: #2196F3;
  color: #fff;
}

.edit-mode-hint {
  font-size: 12px;
  color: #888;
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
  border-top: 1px solid #333;
  border-bottom: 1px solid #333;
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
  color: #888;
  cursor: pointer;
  transition: all 0.2s ease;
}

.interact-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #aaa;
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
  color: #888;
  line-height: 1.2;
}

/* 点赞按钮 */
.interact-btn.like-btn:hover,
.interact-btn.like-btn.active {
  color: #ff6b6b;
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
  color: #2196F3;
}

.interact-btn.sharewatch-btn:hover .btn-icon,
.interact-btn.sharewatch-btn.active .btn-icon {
  background: rgba(33, 150, 243, 0.15);
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
  color: #888;
  cursor: pointer;
  transition: all 0.2s ease;
}

.action-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #aaa;
  transform: scale(1.05);
}

.action-btn.active {
  color: #2196F3;
}

.action-btn.active:hover {
  color: #fff;
}

.action-btn .btn-label {
  display: block;
  font-size: 11px;
  color: #888;
  line-height: 1.2;
}

/* 合集作为分类归属展示 */
.collection-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  background: rgba(33, 150, 243, 0.12);
  color: #64b5f6;
  border-radius: 12px;
  cursor: pointer;
  transition: background 0.2s ease;
}

.collection-meta:hover {
  background: rgba(33, 150, 243, 0.22);
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
  background: #1e1e1e;
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
  color: #ccc;
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
  color: #999;
}

.back-link {
  margin-top: 16px;
  padding: 10px 24px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}

/* 编辑表单 */
.edit-form {
  background: #252525;
  border-radius: 12px;
  padding: 24px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  font-size: 14px;
  color: #999;
  margin-bottom: 8px;
}

/* 标签输入框包装器 */
.tag-input-wrapper {
  position: relative;
}

.tag-input-wrapper input {
  width: 100%;
  padding: 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #252525;
  color: #fff;
  font-size: 14px;
  box-sizing: border-box;
}

.tag-input-wrapper input:focus {
  outline: none;
  border-color: #2196F3;
}

/* 标签智能建议下拉框 */
.tag-suggestions {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #2a2a2a;
  border: 1px solid #444;
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
  border-bottom: 1px solid #333;
  transition: background 0.2s;
}

.tag-suggestion-item:last-child {
  border-bottom: none;
}

.tag-suggestion-item:hover {
  background: #3a3a3a;
}

.suggestion-path {
  color: #fff;
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
  background: #333;
  border: 1px dashed #555;
  border-radius: 50%;
  color: #888;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.tag-add-btn:hover {
  background: #444;
  border-color: #666;
  color: #fff;
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
  border-bottom: 1px solid #333;
  flex-shrink: 0;
}

.dialog-header h3 {
  margin: 0;
  font-size: 18px;
}

.close-btn {
  background: none;
  border: none;
  color: #888;
  font-size: 24px;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.close-btn:hover {
  color: #fff;
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
  border-right: 1px solid #333;
  padding-right: 16px;
}

.panel-title {
  font-size: 13px;
  color: #888;
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
  background: #2a2a2a;
}

.tag-tree-item.active {
  background: #2196F3;
}

.tag-tree-name {
  flex: 1;
  font-size: 14px;
  color: #ccc;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tag-tree-item.active .tag-tree-name {
  color: #fff;
}

.tag-tree-badge {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #666;
  background: #333;
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
  background: #1a1a1a;
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
  color: #555;
  flex-shrink: 0;
}

.breadcrumb-item {
  color: #ccc;
  cursor: pointer;
  flex-shrink: 0;
  max-width: 80px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.breadcrumb-item:hover {
  color: #fff;
}

.breadcrumb-item.active {
  color: #4FC3F7;
  cursor: default;
}

.breadcrumb-back {
  margin-left: auto;
  background: #333;
  border: none;
  color: #888;
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
  background: #444;
  color: #fff;
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
  background: #1a1a1a;
  border-radius: 8px;
  font-size: 13px;
  flex-shrink: 0;
}

.path-label {
  color: #666;
}

.path-value {
  color: #fff;
}

.path-part {
  color: #4FC3F7;
}

.path-separator {
  color: #888;
  margin: 0 2px;
}

.path-placeholder {
  color: #555;
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
  background: #333;
  border: 1px dashed #555;
  border-radius: 8px;
  color: #888;
  font-size: 18px;
  font-weight: bold;
  cursor: pointer;
  transition: all 0.2s;
  flex-shrink: 0;
}

.slash-btn:hover {
  background: #444;
  border-color: #666;
  color: #fff;
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
  border-top: 1px solid #333;
  padding-top: 12px;
  flex-shrink: 0;
  max-height: 200px;
  overflow-y: auto;
}

.video-tags-list-header {
  font-size: 13px;
  color: #888;
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
  background: #252525;
  border-radius: 8px;
  margin-bottom: 8px;
}

.tag-item .tag-name {
  flex: 1;
  color: #ccc;
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
  background: #1a1a1a;
  border: 1px solid #444;
  border-radius: 6px;
  color: #fff;
  font-size: 14px;
}

.tag-edit-input:focus {
  outline: none;
  border-color: #2196F3;
}

.no-tags {
  color: #666;
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
  background: #1a1a2e;
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #888;
}

.clear-filter {
  background: none;
  border: 1px solid #444;
  color: #888;
  padding: 4px 10px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.clear-filter:hover {
  background: #333;
  color: #fff;
  border-color: #555;
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
  background: #2a2a2a;
  border-color: #444;
}

.tag-flat-item.active {
  background: #2196F3;
  border-color: #1976D2;
}

.tag-flat-path {
  font-size: 14px;
  color: #ccc;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
}

.tag-flat-item:hover .tag-flat-path {
  color: #fff;
}

.tag-flat-item.active .tag-flat-path {
  color: #fff;
}

.tag-flat-check {
  font-size: 12px;
  color: #4CAF50;
  margin-left: 8px;
  flex-shrink: 0;
}

.tag-flat-item.active .tag-flat-check {
  color: #fff;
}

/* 添加标签区域 */
.add-tag-section {
  padding-top: 16px;
  border-top: 1px solid #333;
  position: relative;
}

.tag-input-row {
  display: flex;
  gap: 8px;
}

.tag-input {
  flex: 1;
  padding: 10px 12px;
  background: #1a1a1a;
  border: 1px solid #444;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
}

.tag-input:focus {
  outline: none;
  border-color: #2196F3;
}

.tag-hint {
  margin-top: 12px;
  font-size: 12px;
  color: #666;
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
  color: #888;
  cursor: pointer;
  transition: all 0.2s ease;
}

.tag-editor-dialog .btn-icon:hover {
  background: #333;
  color: #fff;
}

.tag-editor-dialog .btn-primary {
  padding: 8px 16px;
  background: #2196F3;
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.tag-editor-dialog .btn-primary:hover {
  background: #1976D2;
}

.form-group input,
.form-group textarea {
  width: 100%;
  padding: 12px;
  border: 1px solid #444;
  border-radius: 8px;
  background: #1a1a1a;
  color: #fff;
  font-size: 15px;
  box-sizing: border-box;
}

.form-group input:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #2196F3;
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
  border: 1px solid #444;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-secondary:hover {
  background: #333;
}

.btn-primary {
  padding: 10px 24px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: #1976D2;
}

.btn-danger {
  padding: 10px 24px;
  background: #f44336;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-danger:hover {
  background: #d32f2f;
}

.edit-btn:hover {
  background: #2196F3;
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
  background: #1a1a1a;
  border-radius: 12px;
  padding: 24px;
  width: 90%;
  max-width: 400px;
}

.dialog h3 {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  margin: 0 0 16px 0;
}

.dialog p {
  color: #ccc;
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
  background: #2a2a2a;
  border-radius: 8px;
}

.dialog-checkbox label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #ccc;
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
  color: #999;
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
  background: #252525;
  border: 1px solid #444;
  border-radius: 8px;
  color: #fff;
  font-size: 13px;
  font-family: monospace;
}

.btn-copy {
  padding: 10px 16px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.2s;
}

.btn-copy:hover {
  background: #1976D2;
}

.share-hint {
  font-size: 13px;
  color: #999;
  line-height: 1.6;
}

.share-status {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #333;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 14px;
}

.status-label {
  color: #999;
}

.status-value {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 13px;
}

.status-value.pending {
  background: #ff9800;
  color: #fff;
}

.status-value.active {
  background: #4caf50;
  color: #fff;
}

/* Toast 提示 */
.toast {
  position: fixed;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.8);
  color: #fff;
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
    border-bottom: 1px solid #333;
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
    background: #252525;
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
  }

  .rec-thumbnail-wrapper {
    width: 100%;
    height: auto;
    aspect-ratio: 16 / 9;
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
    aspect-ratio: 16 / 9;
  }
}
/* 精彩片段标记 */
.markers-section {
  margin: 16px 0;
  padding: 14px 16px;
  background: #161616;
  border: 1px solid #2a2a2a;
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
  color: #fff;
}
.markers-add-btn {
  padding: 6px 12px;
  border: 1px solid #3a5a7a;
  border-radius: 8px;
  background: rgba(33, 150, 243, 0.12);
  color: #9ecbff;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
}
.markers-add-btn:hover:not(:disabled) {
  background: #2196f3;
  color: #fff;
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
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  background: #0f0f0f;
  color: #fff;
  font-size: 14px;
}
.marker-save,
.marker-cancel {
  padding: 0 14px;
  height: 36px;
  border-radius: 8px;
  border: 1px solid #3a3a3a;
  background: #222;
  color: #ddd;
  cursor: pointer;
  font-size: 13px;
}
.marker-save {
  background: #2196f3;
  border-color: #2196f3;
  color: #fff;
}
.marker-save:hover {
  background: #1976d2;
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
  background: #0f0f0f;
  border: 1px solid #262626;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s;
}
.marker-item:hover {
  background: #1c1c1c;
  border-color: #3a5a7a;
}
.marker-time {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  color: #9ecbff;
  font-size: 13px;
  white-space: nowrap;
}
.marker-note {
  flex: 1;
  color: #e0e0e0;
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
  color: #888;
  cursor: pointer;
  font-size: 13px;
}
.marker-del:hover {
  background: #3a2020;
  color: #ff6b6b;
}
.markers-empty {
  margin: 4px 0 0;
  color: #888;
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
  border: 1px solid rgba(255, 255, 255, 0.18);
  background: transparent;
  color: #cbd5e1;
  cursor: pointer;
  user-select: none;
  transition: all 0.15s ease;
}
.qualifier-chip:hover {
  border-color: rgba(105, 219, 255, 0.6);
}
.qualifier-chip.on {
  background: rgba(105, 219, 255, 0.18);
  border-color: #69dbff;
  color: #e7f6ff;
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
  border: 1px dashed rgba(255, 255, 255, 0.28);
  background: rgba(0, 0, 0, 0.25);
  color: #e2e8f0;
  width: 110px;
  outline: none;
}
.qualifier-add-input:focus {
  border-color: #69dbff;
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
  color: #0b1220;
}
</style>
