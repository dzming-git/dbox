<script setup lang="ts">
defineOptions({ name: 'Home' })
import { ref, onMounted, onUnmounted, computed, watch, onActivated, onDeactivated } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import { useGalleryStore } from '../stores/galleryStore'
import { useUserStore } from '../stores/userStore'
import { videoApi } from '../api'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import { useSavedViews } from '../composables/useSavedViews'
import { useToast } from '../composables/useToast'
import VideoCard from '../components/VideoCard.vue'
import TagBadge from '../components/TagBadge.vue'
import ItemEditDrawer from '../components/ItemEditDrawer.vue'
import ResourceListRow from '../components/ResourceListRow.vue'
import ResourceFilterBar from '../components/ResourceFilterBar.vue'
import Gallerys from './Gallerys.vue'
import Posts from './Posts.vue'
import Texts from './Texts.vue'
import { useWatchLaterStore } from '../stores/watchLaterStore'
import { withThumbToken } from '../utils/media'
import { formatDuration } from '../utils/format'
import type { Video, Tag } from '../types'
import { MEDIA_TABS, type MediaTab } from '../constants/mediaTabs'

const router = useRouter()
const route = useRoute()
const watchLaterStore = useWatchLaterStore()
const { showToast } = useToast()

// 首页媒体类型切换：视频 / 图集 对等展示，模式写入 URL（?mode=video|gallery）
const mediaTab = ref<'video' | 'gallery' | 'mixed' | 'text'>(route.query.mode === 'gallery' ? 'gallery' : (route.query.mode === 'mixed' ? 'mixed' : (route.query.mode === 'text' ? 'text' : 'video')))

// 切换媒体模式时同步到 URL，并从 URL 回读（支持前进/后退、直接分享链接）
// 切换模式时清空与模式绑定的其他参数（排序、页码、筛选、搜索等），仅保留 mode，使其恢复默认。
watch(mediaTab, (val) => {
  if (route.query.mode !== val) {
    router.replace({ query: { mode: val } })
  }
})
watch(
  () => route.query.mode,
  (val) => {
    const m = val === 'gallery' ? 'gallery' : (val === 'mixed' ? 'mixed' : (val === 'text' ? 'text' : 'video'))
    if (mediaTab.value !== m) mediaTab.value = m
  }
)

const videoStore = useVideoStore()
const userStore = useUserStore()

const loading = computed(() => videoStore.loading)
const videos = computed(() => videoStore.videos)
const tags = computed(() => videoStore.tags)

// 返回顶部：把上次在详情页查看过的视频置顶到随机推荐第一个
const displayVideos = computed(() => {
  const list = [...videos.value]
  try {
    const last = sessionStorage.getItem('lastViewedVideo')
    if (last) {
      const idx = list.findIndex((v) => v.hash === last)
      if (idx > 0) {
        const [item] = list.splice(idx, 1)
        list.unshift(item)
      }
      sessionStorage.removeItem('lastViewedVideo')
    }
  } catch {}
  return list
})
const selectedTagId = computed(() => videoStore.selectedTagId)
const selectedUntagged = computed(() => videoStore.selectedUntagged)
// 「未标记（待整理）」视频数量，仅在展开标签面板时拉取，不在主界面暴露
const untaggedCount = ref(0)
const fetchUntaggedCount = async () => {
  try {
    const params: any = { untagged: 1, limit: 1 }
    if (selectedLibraryId.value) params.library_id = selectedLibraryId.value
    const res = await videoApi.getVideos(params) as any
    untaggedCount.value = res.total || 0
  } catch {
    untaggedCount.value = 0
  }
}
const selectedLibraryId = computed(() => videoStore.selectedLibraryId)
const libraries = computed(() => videoStore.libraries)
const noLibraries = computed(() => !loading.value && libraries.value.length === 0)

// 标签区域折叠状态
const showTagsSection = ref(false)

// 详细筛选面板：默认收起。
// 排序/资源库/合集/关键词/标签/视图这一整套平铺在顶栏会长期占据首屏，
// 收进面板后顶栏只留「媒体类型 + 一个入口」，需要时再展开。
const filterPanelOpen = ref(false)
// 面板收起时也要能看出「筛选正在生效」，否则用户会以为列表莫名变少了
const activeFilterCount = computed(() => {
  let n = 0
  if (videoStore.selectedTagId.value) n++
  if (videoStore.selectedUntagged.value) n++
  if (videoStore.selectedLibraryId.value) n++
  if (videoStore.selectedCollectionId.value) n++
  if (videoStore.minDuration.value != null) n++
  if (videoStore.maxDuration.value != null) n++
  if (videoStore.unwatchedDays.value) n++
  if ((videoStore.searchQuery.value || '').trim()) n++
  return n
})

// 标签树导航
const allTagsTree = ref<any[]>([])
const currentTagLevel = ref<any[]>([])
const tagBreadcrumbs = ref<any[]>([])

// 构建标签树
const buildTagTree = (tags: any[]): any[] => {
  const tagMap = new Map<number, any>()
  const rootTags: any[] = []

  tags.forEach(tag => {
    tagMap.set(tag.id, { ...tag, children: [] })
  })

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

// 初始化标签树
const initTagTree = async () => {
  if (tags.value.length > 0 && allTagsTree.value.length === 0) {
    allTagsTree.value = buildTagTree(tags.value)
    currentTagLevel.value = allTagsTree.value
  }
}

// 进入标签层级
const enterTagLevel = (tag: any) => {
  if (tag.children && tag.children.length > 0) {
    currentTagLevel.value = tag.children
    tagBreadcrumbs.value.push({ id: tag.id, name: tag.name, path: tag.path || tag.name })
  }
}

// 返回上级
const goBackTagLevel = () => {
  if (tagBreadcrumbs.value.length === 0) return

  tagBreadcrumbs.value.pop()
  if (tagBreadcrumbs.value.length === 0) {
    currentTagLevel.value = allTagsTree.value
  } else {
    const parentPath = tagBreadcrumbs.value.map(b => b.name).join('/')
    const findLevel = (nodes: any[], path: string): any[] | null => {
      for (const node of nodes) {
        if ((node.path || node.name) === path && node.children) {
          return node.children
        }
        if (node.children) {
          const found = findLevel(node.children, path)
          if (found) return found
        }
      }
      return null
    }
    const level = findLevel(allTagsTree.value, parentPath)
    currentTagLevel.value = level || allTagsTree.value
  }
}

// 返回根级别
const goToRootLevel = () => {
  tagBreadcrumbs.value = []
  currentTagLevel.value = allTagsTree.value
}

// 点击标签
const handleTagClick = (tag: any) => {
  // 选中该标签并筛选（无论是否有子标签都写入 URL，与标签页眼睛图标保持一致）
  videoStore.filterByTag(tag.id)
  if (tag.children && tag.children.length > 0) {
    // 有子标签：展开下一级便于继续浏览，同时按当前标签筛选
    enterTagLevel(tag)
    showTagsSection.value = true
  } else {
    // 叶子标签：直接筛选并收起标签区
    showTagsSection.value = false
  }
  updateUrl()
}

// 点击"全部"标签
const handleClearTag = () => {
  videoStore.filterByTag(null)
  showTagsSection.value = false
  updateUrl()
}

// 点击"未标记（待整理）"——与标签筛选互斥，再次点击取消
const handleUntaggedClick = () => {
  videoStore.filterByUntagged(!selectedUntagged.value)
  updateUrl()
}

// 监听 showTagsSection 变化，初始化树
watch(showTagsSection, (newVal) => {
  if (newVal) {
    // 每次展开时重新初始化
    allTagsTree.value = buildTagTree(tags.value)
    currentTagLevel.value = allTagsTree.value
    tagBreadcrumbs.value = []
    // 展开时拉取「未标记」数量（低调呈现，不常驻主界面）
    fetchUntaggedCount()
  }
})

// 监听路由 query 变化（处理浏览器后退/URL直接访问场景）
// suppressQueryWatch：当 URL 是由页面自身 updateUrl() 主动 push（已自行拉取数据）时置位，
// 避免 route.query 变化再次触发 initFromQuery 造成重复请求/闪烁。
const suppressQueryWatch = ref(false)
watch(() => route.query, async (newQuery) => {
  // 自身触发的 URL 同步，跳过恢复
  if (suppressQueryWatch.value) {
    suppressQueryWatch.value = false
    return
  }
  // 如果 query 包含 from，说明是从视频页返回，不需要重新初始化
  if (newQuery.from) return
  // 从 URL 恢复状态（空 query 也走这里，会重置筛选/排序等到默认，
  // 保证浏览器后退到无参数首页时，列表与 URL 保持一致）
  await videoStore.initFromQuery(newQuery as Record<string, string>)
}, { immediate: false })

// 更新 URL query 参数
// 使用 push 而非 replace：让每次筛选/排序/搜索都成为一条独立的浏览器历史记录，
// 用户点击「后退」会返回上一次的筛选状态（而不是直接退出 DBox）。
const updateUrl = () => {
  const query = videoStore.toQuery()
  // 始终保留当前媒体模式，避免换页/筛选后 mode 丢失导致切换 tab 消失
  query.mode = mediaTab.value
  // 标记为本页面主动同步，避免 route.query 监听器重复恢复数据
  suppressQueryWatch.value = true
  router.push({ path: '/', query })
}

// 排序选项
const sortOptions = [
  { value: 'recommended', label: '推荐' },
  { value: 'name', label: '视频名' },
  { value: 'created_at', label: '文件时间' },
  { value: 'view_count', label: '播放量' },
  { value: 'like_count', label: '点赞数' },
  { value: 'download_count', label: '下载数' }
]

const currentSort = computed(() => videoStore.sortBy)
const currentOrder = computed(() => videoStore.sortOrder)

// 通用筛选栏抛出的是「值」而非 DOM 事件（组件不制造伪事件）
const handleSortChange = (value: string) => {
  videoStore.setSortBy(value)
  updateUrl()
}

const handleOrderChange = (value: string) => {
  videoStore.setSortOrder(value)
  updateUrl()
}

// 按资源库筛选
const handleLibraryChange = (val: any) => {
  videoStore.filterByLibrary(val === '' || val == null ? null : parseInt(String(val)))
  updateUrl()
}

// 关键词：本地输入，回车或清除时才应用，避免每敲一个字就打一次接口
// tabs 条由各资源视图自己渲染（见 constants/mediaTabs.ts 的说明），
// Home 只负责把切换请求落到 mediaTab 上。
const onTabChange = (key: string) => { mediaTab.value = key as MediaTab }
const onViewChange = (mode: 'grid' | 'list') => { videoStore.setViewMode(mode) }

const filterKeyword = ref(videoStore.searchQuery || '')
watch(() => videoStore.searchQuery, (v) => { filterKeyword.value = v || '' })

// 通用筛选栏提交搜索时直接把关键词抛出（内部维护 draft，回车才生效）
function onFilterSearch(kw: string) {
  filterKeyword.value = kw
  applyKeyword()
}

function applyKeyword() {
  videoStore.searchVideos(filterKeyword.value.trim())
  updateUrl()
}
function clearKeyword() {
  filterKeyword.value = ''
  applyKeyword()
}

// 按模式内合集筛选
const handleCollectionChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  const val = target.value
  videoStore.filterByCollection(val === '' ? null : parseInt(val))
  updateUrl()
}

// 一键清空所有筛选条件（排序与显示方式不属于筛选，保留）
async function handleClearFilters() {
  filterKeyword.value = ''
  activeViewId.value = ''
  await videoStore.clearFilters()
  updateUrl()
}

// ============ 保存的视图 ============
const { views: savedViews, load: loadSavedViews, save: saveView, remove: removeView } =
  useSavedViews()
const activeViewId = ref('')

// 当前生效的一组筛选条件（供另存为视图）
const currentFilters = () => ({
  libraryId: videoStore.selectedLibraryId,
  collectionId: videoStore.selectedCollectionId,
  tagId: videoStore.selectedUntagged ? null : videoStore.selectedTagId,
  untagged: videoStore.selectedUntagged,
  search: videoStore.searchQuery || '',
  minDuration: videoStore.minDuration,
  maxDuration: videoStore.maxDuration,
  unwatchedDays: videoStore.unwatchedDays,
  sortBy: videoStore.sortBy,
  sortOrder: videoStore.sortOrder,
})

async function handleSaveView() {
  const name = prompt('给这组筛选条件起个名字（例如：最近一个月没看的长视频）')
  if (!name) return
  try {
    const v = await saveView(name, currentFilters())
    if (v) {
      activeViewId.value = v.id
      showToast(`已保存视图「${v.name}」`)
    }
  } catch (e) {
    showToast('保存视图失败')
  }
}

async function handleApplyView(e: Event) {
  const id = (e.target as HTMLSelectElement).value
  activeViewId.value = id
  if (!id) return
  const view = savedViews.value.find((v) => v.id === id)
  if (!view) return
  const f = view.filters || {}
  videoStore.selectedLibraryId = f.libraryId ?? null
  videoStore.selectedCollectionId = f.collectionId ?? null
  videoStore.selectedUntagged = !!f.untagged
  videoStore.selectedTagId = f.untagged ? null : (f.tagId ?? null)
  videoStore.minDuration = f.minDuration ?? null
  videoStore.maxDuration = f.maxDuration ?? null
  videoStore.unwatchedDays = f.unwatchedDays ?? null
  filterKeyword.value = f.search || ''
  videoStore.searchQuery = f.search || ''
  if (f.sortBy) videoStore.sortBy = f.sortBy
  if (f.sortOrder) videoStore.sortOrder = f.sortOrder
  await videoStore.fetchVideos(true)
  updateUrl()
}

async function handleDeleteView() {
  const view = savedViews.value.find((v) => v.id === activeViewId.value)
  if (!view) return
  if (!confirm(`删除视图「${view.name}」？`)) return
  await removeView(view.id)
  activeViewId.value = ''
  showToast(`已删除视图「${view.name}」`)
}

onMounted(async () => {
  // 加载继续观看（本地观看历史）
  loadContinueWatching()
  // 如果 URL 有 query 参数，从其中恢复状态
  if (Object.keys(route.query).length > 0) {
    await Promise.all([
      videoStore.initFromQuery(route.query as Record<string, string>),
      videoStore.fetchTags(),
      videoStore.fetchUserLibraries(),
      videoStore.fetchCollections(),
      loadSavedViews()
    ])
  } else {
    await Promise.all([
      videoStore.fetchVideos(true),
      videoStore.fetchTags(),
      videoStore.fetchUserLibraries(),
      videoStore.fetchCollections(),
      loadSavedViews()
    ])
  }
  // 通过分享链接或标签页眼睛图标进入时，若带 tag 参数，自动展开标签面板以显示当前筛选状态
  if (route.query.tag || route.query.untagged === '1') {
    showTagsSection.value = true
  }
})

const handleVideoClick = (video: Video) => {
  // 把当前首页状态编码为 from 参数，视频页返回时使用
  const homeQuery = videoStore.toQuery()
  const fromQuery: Record<string, string> = {}
  if (Object.keys(homeQuery).length > 0) {
    fromQuery.from = btoa(JSON.stringify(homeQuery))
  }
  router.push({ name: 'Video', params: { hash: video.hash }, query: fromQuery })
}

// ============ 继续观看（用户主动加入的列表，存于 localStorage） ============
const continueWatching = ref<any[]>([])
const continueExpanded = ref(false)   // 默认收起，点击展开
const CONTINUE_WATCH_MAX = 8          // 展开后最多显示的数量，避免遮挡界面

// 缩略图加载失败时的占位图（内联 SVG，无需额外文件）
const PLACEHOLDER_THUMB =
  'data:image/svg+xml;utf8,' + encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" width="320" height="180">' +
    '<rect width="100%" height="100%" fill="#222"/>' +
    '<text x="50%" y="50%" fill="#666" font-size="14" text-anchor="middle" dominant-baseline="middle">无缩略图</text>' +
    '</svg>'
  )

const onContinueImgError = (e: Event) => {
  const img = e.target as HTMLImageElement
  img.onerror = null
  img.src = PLACEHOLDER_THUMB
}

const loadContinueWatching = async () => {
  let list: any[] = []
  try {
    const raw = localStorage.getItem('continueWatch')
    if (raw) list = JSON.parse(raw) || []
  } catch {
    list = []
  }

  if (!Array.isArray(list) || list.length === 0) {
    continueWatching.value = []
    return
  }

  // 按最近加入 / 操作时间倒序
  list.sort((a: any, b: any) => (b.updated_at || 0) - (a.updated_at || 0))

  // 以后端权威数据重建：过滤失效视频，刷新标题 / 缩略图
  try {
    const hashes = list.map((x: any) => x.hash)
    const res: any = await videoApi.getVideosByHashes(hashes)
    const videos = (res && res.videos) || []
    const items = videos.map((v: any) => {
      const meta = list.find((x: any) => x.hash === v.hash) || {}
      return {
        hash: v.hash,
        title: v.title || meta.title || '',
        thumbnail: v.thumbnail || `/thumbnail/${v.hash}`,
        duration: v.duration || meta.duration || 0,
        progress: meta.progress || 0
      }
    })
    continueWatching.value = items
    return
  } catch {
    // 接口失败（如未登录）时回退到本地数据
  }

  continueWatching.value = list.map((x: any) => ({
    hash: x.hash,
    title: x.title || '',
    thumbnail: x.thumbnail || x.cover_url || `/thumbnail/${x.hash}`,
    duration: x.duration || 0,
    progress: x.progress || 0
  }))
}

const continueWatch = (item: any) => {
  router.push({ path: `/video/${item.hash}`, query: { t: Math.floor(item.progress || 0) } })
}

// 继续观看进度百分比
const progressPercent = (item: any) => {
  if (!item.duration) return 0
  return Math.min(100, Math.round((item.progress / item.duration) * 100))
}

// ============ 批量选择 ============
// 编辑模式（抽屉编辑单条）
const editMode = ref(false)
const editDrawerVisible = ref(false)
const editingItem = ref<any>(null)


// ============ 编辑模式（抽屉编辑单条） ============
const toggleEditMode = () => {
  editMode.value = !editMode.value
}

const openEdit = (video: any) => {
  editingItem.value = video
  editDrawerVisible.value = true
}

// 正常模式下点击卡片上的 tag → 按该 tag 筛选视频
const onTagClick = (tag: any) => {
  if (editMode.value) return
  let id = tag.id
  // 通过抽屉新增的标签可能缺少 id，按名称在标签表中回查
  if (id == null && tag.name) {
    const found = videoStore.tags.find((t: any) => t.name === tag.name)
    if (found) id = found.id
  }
  if (id != null) {
    videoStore.filterByTag(id)
    // 与侧边标签导航、标签页眼睛图标保持一致：筛选后写入 URL
    updateUrl()
  }
}

// 抽屉保存后就地更新列表中的该条数据
const onEditSaved = (updated: any) => {
  const idx = videoStore.videos.findIndex((v) => v.hash === updated.hash)
  if (idx !== -1) {
    videoStore.videos[idx] = { ...videoStore.videos[idx], ...updated }
  }
}

// ============ 分页相关 ============
const currentPage = computed(() => {
  return Math.floor(videoStore.pagination.offset / videoStore.pagination.limit) + 1
})

const totalPages = computed(() => {
  return Math.ceil(videoStore.pagination.total / videoStore.pagination.limit) || 1
})

const goToPage = async (page: number) => {
  if (page < 1 || page > totalPages.value) return
  // 乐观更新高亮，避免等待请求期间页码跳动
  videoStore.pagination.offset = (page - 1) * videoStore.pagination.limit
  // 只更新 URL（page 写入 query），由 route.query 监听负责拉取对应页数据，
  // 避免直接拉取与 updateUrl 触发 watcher 造成的重复请求与页码回退。
  // 始终带上 page 参数，确保切换到第 1 页时 watcher 也能正确触发重新拉取。
  const query = videoStore.toQuery()
  query.page = String(page)
  // 保留当前媒体模式，避免换页后 mode 丢失导致切换 tab 消失
  query.mode = mediaTab.value
  router.push({ path: '/', query })
}

const prevPage = async () => {
  if (currentPage.value > 1) {
    await goToPage(currentPage.value - 1)
  }
}

const nextPage = async () => {
  if (currentPage.value < totalPages.value) {
    await goToPage(currentPage.value + 1)
  }
}

// 页码显示范围（确保首页和末页常驻）
const pageRange = computed(() => {
  const current = currentPage.value
  const total = totalPages.value
  const range: (number | null)[] = []

  if (total <= 7) {
    // 总页数 <= 7，直接显示所有页码
    for (let i = 1; i <= total; i++) {
      range.push(i)
    }
  } else {
    // 总页数 > 7，显示 [1, ..., start, ..., end, ..., total]
    const start = Math.max(2, current - 1)
    const end = Math.min(total - 1, current + 1)

    range.push(1) // 首页

    if (start > 2) {
      range.push(null) // 省略号
    }

    for (let i = start; i <= end; i++) {
      range.push(i)
    }

    if (end < total - 1) {
      range.push(null) // 省略号
    }

    range.push(total) // 末页
  }

  return range
})

const shuffling = ref(false)

// 顶部下拉刷新：推荐排序下等效「换一批」（重新随机排序），其余排序保持原规则原地刷新
const galleryStore = useGalleryStore()
const postsRef = ref<any>(null)
const textsRef = ref<any>(null)
const ptr = usePullToRefresh()

async function ptrRefresh() {
  if (mediaTab.value === 'video') {
    if (videoStore.sortBy === 'recommended') {
      await videoStore.shuffleVideos()
    } else {
      // 非推荐排序：保留当前排序规则刷新，不重置为推荐、不弹出撤回
      await videoStore.fetchVideos(true)
    }
  } else if (mediaTab.value === 'gallery') {
    await galleryStore.fetchGallerys(true)
  } else if (mediaTab.value === 'mixed') {
    postsRef.value?.reload?.()
  } else if (mediaTab.value === 'text') {
    textsRef.value?.reload?.()
  }
}

function registerPtr() {
  // 仅推荐排序的下拉刷新才是「换一批」语义，其余均为普通刷新
  ptr.setHandler(ptrRefresh, videoStore.sortBy === 'recommended' ? 'shuffle' : 'reload')
}

onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())
// 切换媒体类型或排序后，下拉刷新的语义（换一批 / 刷新）随之变化
watch(mediaTab, registerPtr)
watch(() => videoStore.sortBy, registerPtr)

const handleUndo = async () => {
  shuffling.value = true
  await videoStore.undoShuffle()
  shuffling.value = false
}

const hasPreviousVideos = computed(() => videoStore.previousVideos && videoStore.previousVideos.length > 0)

// PC 端专用：桌面端没有下拉手势，用按钮触发刷新/换一批（与移动端下拉刷新语义一致）
async function handlePcRefresh() {
  shuffling.value = true
  try {
    await ptrRefresh()
  } finally {
    shuffling.value = false
  }
}

const videoListMeta = (video: Video): string[] => {
  const meta = [`${video.view_count} 次播放`]
  if (video.like_count > 0) meta.push(`♥ ${video.like_count}`)
  return meta
}

// 列表模式的缩略图地址（带登录 token 鉴权）
const listThumbUrl = (video: Video): string => {
  const base = video.thumbnail || '/placeholder.jpg'
  return withThumbToken(base)
}
</script>

<template>
  <div class="home-container">
    <!-- 首屏引导：尚无资源库时引导用户添加/上传/扫描 -->
    <div class="onboarding-banner" v-if="noLibraries">
      <div class="ob-icon">
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M3 7l9-4 9 4-9 4-9-4z"/>
          <path d="M3 12l9 4 9-4M3 17l9 4 9-4"/>
        </svg>
      </div>
      <div class="ob-body">
        <div class="ob-title">欢迎使用，先添加你的媒体库</div>
        <div class="ob-desc">当前还没有可用的资源库，按以下步骤即可开始观看：</div>
        <div class="ob-steps">
          <div class="ob-step">
            <span class="ob-num">1</span>
            <div>
              <div class="ob-step-title">添加资源库</div>
              <div class="ob-step-desc">在「资源库」页面关联本地文件夹</div>
            </div>
          </div>
          <div class="ob-step">
            <span class="ob-num">2</span>
            <div>
              <div class="ob-step-title">上传内容</div>
              <div class="ob-step-desc">单文件或分片上传视频 / 图集</div>
            </div>
          </div>
          <div class="ob-step">
            <span class="ob-num">3</span>
            <div>
              <div class="ob-step-title">自动扫描</div>
              <div class="ob-step-desc">监控文件夹，新增文件自动入库</div>
            </div>
          </div>
        </div>
        <div class="ob-actions">
          <router-link class="ob-btn ob-primary" to="/libraries">添加资源库</router-link>
          <router-link class="ob-btn" to="/upload">去上传</router-link>
        </div>
      </div>
    </div>

    <!-- 视频工具条：只在本 tab 渲染。
         其它资源（图集/文本/帖子）各自渲染自己的工具条——筛选面板的内容属于
         资源自身，若这里再统一渲染一份，图集页就会出现两个「筛选」按钮。 -->
    <ResourceFilterBar
      v-if="mediaTab === 'video'"
      v-model:open="filterPanelOpen"
      :tabs="MEDIA_TABS"
      :tab="mediaTab"
      :sorts="sortOptions"
      :sort="currentSort"
      :order="currentOrder"
      :libraries="libraries"
      :library-id="selectedLibraryId"
      :keyword="filterKeyword"
      :view-mode="videoStore.viewMode"
      :active-count="activeFilterCount"
      @tab-change="onTabChange"
      @sort-change="handleSortChange"
      @order-change="handleOrderChange"
      @library-change="handleLibraryChange"
      @search="onFilterSearch"
      @clear-search="clearKeyword"
      @view-change="onViewChange"
    >
      <template #scope>
        <!-- 合集：与资源库同属「归属」维度 -->
        <select
          class="rf-select"
          :value="videoStore.selectedCollectionId || ''"
          @change="handleCollectionChange"
          title="按模式内合集筛选"
        >
          <option value="">全部合集</option>
          <option v-for="c in videoStore.collections" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </template>
      <template #extra>
        <!-- 保存的视图：把当前这组条件存下来，下次一键套用 -->
        <div class="rf-row">
          <span class="rf-label">视图</span>
          <select
            v-if="savedViews.length"
            class="rf-select"
            :value="activeViewId"
            @change="handleApplyView"
            title="套用已保存的视图"
          >
            <option value="">保存的视图</option>
            <option v-for="v in savedViews" :key="v.id" :value="v.id">{{ v.name }}</option>
          </select>
          <button
            class="rf-btn"
            :disabled="!videoStore.hasActiveFilters"
            @click="handleSaveView"
            :title="videoStore.hasActiveFilters ? '把当前筛选条件存为视图' : '先选择筛选条件'"
          >另存为视图</button>
          <button v-if="activeViewId" class="rf-btn" @click="handleDeleteView" title="删除当前视图">删除视图</button>
          <button
            v-if="videoStore.hasActiveFilters"
            class="rf-btn"
            @click="handleClearFilters"
            title="清空所有筛选条件"
          >清空筛选</button>
        </div>
        <!-- 标签：数量可能很多，面板内再折叠一次；标签树本身渲染在面板下方 -->
        <div class="rf-row">
          <button class="rf-btn" @click="showTagsSection = !showTagsSection">
            {{ showTagsSection ? '收起标签' : '展开标签筛选' }}
            <span v-if="selectedUntagged" class="selected-tag-name">(未标记)</span>
            <span v-else-if="selectedTagId" class="selected-tag-name">
              ({{ tags.find(t => t.id === selectedTagId)?.name || '已选标签' }})
            </span>
          </button>
        </div>
      </template>
      <template #actions>
        <button
          v-if="hasPreviousVideos && currentSort === 'recommended'"
          class="rf-btn"
          :disabled="shuffling"
          @click="handleUndo"
          title="回到上一批推荐"
        >撤回</button>
        <button
          class="rf-btn"
          :disabled="shuffling"
          @click="handlePcRefresh"
          :title="currentSort === 'recommended' ? '换一批推荐内容' : '刷新列表'"
        >{{ currentSort === 'recommended' ? '换一批' : '刷新' }}</button>
        <button
          class="rf-btn"
          :class="{ active: editMode }"
          @click="toggleEditMode"
        >{{ editMode ? '退出编辑' : '编辑' }}</button>
      </template>
    </ResourceFilterBar>

    <!-- 标签区域 - 可折叠（现在收在筛选面板内） -->
    <div v-if="filterPanelOpen && showTagsSection && mediaTab === 'video'" class="tags-section">
      <!-- 面包屑导航 -->
      <div class="tag-tree-nav">
        <div class="tag-breadcrumb" v-if="tagBreadcrumbs.length > 0">
          <span class="breadcrumb-root" @click="goToRootLevel">根</span>
          <template v-for="(crumb, idx) in tagBreadcrumbs" :key="crumb.id">
            <span class="breadcrumb-sep">/</span>
            <span
              class="breadcrumb-item"
              :class="{ active: idx === tagBreadcrumbs.length - 1 }"
              @click="goBackTagLevel"
            >{{ crumb.name }}</span>
          </template>
        </div>

        <!-- 返回按钮 -->
        <button
          v-if="tagBreadcrumbs.length > 0"
          class="nav-back-btn"
          @click="goBackTagLevel"
          title="返回上级"
        >
          ‹ 返回
        </button>
      </div>

      <!-- 标签列表 -->
      <div class="tags-container">
        <!-- 全部按钮 -->
        <div
          class="tag-nav-item all-tag"
          :class="{ active: selectedTagId === null && !selectedUntagged }"
          @click="handleClearTag"
        >
          <span class="tag-nav-name">全部</span>
        </div>

        <!-- 未标记（待整理）：低调呈现，仅在展开标签面板时出现 -->
        <div
          v-if="untaggedCount > 0"
          class="tag-nav-item untagged-tag"
          :class="{ active: selectedUntagged }"
          @click="handleUntaggedClick"
          title="查看还没有打标签的视频"
        >
          <span class="tag-nav-name">未标记</span>
          <span class="tag-nav-badge untagged-badge">{{ untaggedCount }}</span>
        </div>

        <!-- 当前层级的标签 -->
        <div
          v-for="tag in currentTagLevel"
          :key="tag.id"
          class="tag-nav-item"
          :class="{ active: selectedTagId === tag.id }"
          @click="handleTagClick(tag)"
        >
          <span class="tag-nav-name">{{ tag.name }}</span>
          <span v-if="tag.children && tag.children.length > 0" class="tag-nav-badge">
            {{ tag.children.length }}
            <span class="tag-nav-arrow">›</span>
          </span>
        </div>

        <p v-if="currentTagLevel.length === 0" class="no-tags">该分类下暂无标签</p>
      </div>
    </div>

    <!-- 视频内容（仅视频 tab 显示） -->
    <div v-if="mediaTab === 'video'">

    <!-- 继续观看（默认收起，可点击展开；数量受控） -->
    <div v-if="continueWatching.length > 0" class="continue-section">
      <div class="continue-header" :class="{ expanded: continueExpanded }" @click="continueExpanded = !continueExpanded">
        <div class="continue-title-row">
          <svg class="chev" :class="{ open: continueExpanded }" viewBox="0 0 24 24" width="18" height="18">
            <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <h2 class="section-title">继续观看</h2>
          <span class="continue-count">{{ continueWatching.length }}</span>
        </div>
        <span class="continue-hint">{{ continueExpanded ? '收起' : `展开全部 (${continueWatching.length})` }}</span>
      </div>
      <div v-show="continueExpanded" class="video-grid">
        <div
          v-for="item in continueWatching.slice(0, CONTINUE_WATCH_MAX)"
          :key="item.hash"
          class="continue-card"
          @click="continueWatch(item)"
          data-testid="continue-card"
        >
          <div class="continue-thumb">
            <img :src="withThumbToken(item.thumbnail)" :alt="item.title" @error="onContinueImgError" />
            <span class="continue-duration">{{ formatDuration(item.duration) }}</span>
            <div class="continue-progress">
              <div class="continue-progress-bar" :style="{ width: progressPercent(item) + '%' }"></div>
            </div>
          </div>
          <div class="continue-info">
            <h3 class="continue-title">{{ item.title }}</h3>
            <span class="continue-pct">已看 {{ progressPercent(item) }}%</span>
          </div>
        </div>
      </div>
      <p v-if="continueExpanded && continueWatching.length > CONTINUE_WATCH_MAX" class="continue-more">仅显示最近 {{ CONTINUE_WATCH_MAX }} 个</p>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 视频网格 - 所有视频统一显示 -->
    <template v-else>
      <div v-if="videos.length > 0" class="video-section">
        <!-- 缩略图模式 -->
        <div v-if="videoStore.viewMode === 'grid'" class="video-grid">
          <VideoCard
            v-for="video in displayVideos"
            :key="video.hash"
            :video="video"
            :editable="editMode"
            @click="handleVideoClick(video)"
            @edit="openEdit"
            @tag-click="onTagClick"
          />
        </div>
        <!-- 列表模式 -->
        <div v-else class="video-list">
          <ResourceListRow
            v-for="video in displayVideos"
            :key="video.hash"
            type="video"
            :item="video"
            :thumb-url="listThumbUrl(video)"
            :meta="videoListMeta(video)"
            :badge="video.duration ? formatDuration(video.duration) : ''"
            :edit-mode="editMode"
            @click="handleVideoClick"
            @edit="openEdit"
          />
        </div>
      </div>

      <!-- 移动端单手翻页：底部悬浮的上一页 / 下一页 -->
      <div v-if="mediaTab === 'video' && totalPages > 1 && currentSort !== 'recommended'" class="mobile-pager">
        <button class="page-btn mobile-page-btn" :disabled="currentPage === 1" @click="prevPage">‹ 上一页</button>
        <span class="mobile-page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
        <button class="page-btn mobile-page-btn" :disabled="currentPage === totalPages" @click="nextPage">下一页 ›</button>
      </div>

      <!-- 空状态 -->
      <div v-if="videos.length === 0" class="empty-state">
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1">
          <rect x="2" y="4" width="20" height="16" rx="2"/>
          <path d="M10 9l5 3-5 3V9z"/>
        </svg>
        <p>暂无视频</p>
      </div>

      <!-- 分页组件 -->
      <div v-if="totalPages > 1 && currentSort !== 'recommended'" class="pagination">
        <button class="page-btn" :disabled="currentPage === 1" @click="goToPage(1)">
          首页
        </button>
        <button class="page-btn" :disabled="currentPage === 1" @click="prevPage">
          ‹ 上一页
        </button>
        <template v-for="page in pageRange" :key="page">
          <button
            v-if="page"
            class="page-btn"
            :class="{ active: page === currentPage }"
            @click="goToPage(page)"
          >
            {{ page }}
          </button>
          <span v-else class="page-ellipsis">...</span>
        </template>
        <button class="page-btn" :disabled="currentPage === totalPages" @click="nextPage">
          下一页 ›
        </button>
        <button class="page-btn" :disabled="currentPage === totalPages" @click="goToPage(totalPages)">
          末页
        </button>
        <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
      </div>
    </template>
    </div>
    <!-- 图集内容（仅图集 tab 显示） -->
    <Gallerys
      v-else-if="mediaTab === 'gallery'"
      :media-tab="mediaTab"
      @tab-change="onTabChange"
    />
    <!-- 帖子（Post）：通过资源索引表自由引用视频 / 图片集的策展信息流 -->
    <Posts
      v-else-if="mediaTab === 'mixed'"
      ref="postsRef"
      :media-tab="mediaTab"
      @tab-change="onTabChange"
    />
    <!-- 文本模式（未来内容管理，复用同一套资源索引机制） -->
    <Texts
      v-else-if="mediaTab === 'text'"
      ref="textsRef"
      :media-tab="mediaTab"
      @tab-change="onTabChange"
    />

    <!-- 编辑抽屉（视频/图集通用） -->
    <ItemEditDrawer
      :visible="editDrawerVisible"
      type="video"
      :item="editingItem"
      @update:visible="editDrawerVisible = $event"
      @saved="onEditSaved"
    />
  </div>
</template>

<style scoped>
.home-container {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* 首屏引导 */
.onboarding-banner {
  display: flex;
  gap: 20px;
  align-items: flex-start;
  background: linear-gradient(135deg, var(--border-default), var(--bg-surface-2));
  border: 1px solid var(--border-default);
  border-radius: 14px;
  padding: 24px;
  margin-bottom: 20px;
}

.ob-icon {
  flex: 0 0 auto;
  color: #ff4d6d;
  background: rgba(255, 77, 109, 0.12);
  border-radius: 12px;
  padding: 12px;
}

.ob-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text-primary);
  margin-bottom: 4px;
}

.ob-desc {
  color: var(--text-secondary);
  font-size: 14px;
  margin-bottom: 16px;
}

.ob-steps {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  margin-bottom: 18px;
}

.ob-step {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  flex: 1 1 180px;
  min-width: 160px;
}

.ob-num {
  flex: 0 0 auto;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  background: #ff4d6d;
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.ob-step-title {
  color: var(--text-primary);
  font-size: 14px;
  font-weight: 600;
}

.ob-step-desc {
  color: var(--text-tertiary);
  font-size: 12px;
  margin-top: 2px;
}

.ob-actions {
  display: flex;
  gap: 12px;
}

.ob-btn {
  display: inline-block;
  padding: 9px 18px;
  border-radius: 8px;
  font-size: 14px;
  text-decoration: none;
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-default);
  transition: background 0.2s;
}

.ob-btn:hover {
  background: var(--bg-surface-hover);
}

.ob-primary {
  background: #ff4d6d;
  color: var(--text-primary);
  border-color: #ff4d6d;
}

.ob-primary:hover {
  background: #ff3a5c;
}

@media (max-width: 768px) {
  .onboarding-banner {
    flex-direction: column;
  }
  .ob-actions {
    flex-direction: column;
  }
  .ob-btn {
    text-align: center;
  }
}

/* 首页媒体类型切换：视频 / 图集 对等 */

/* 顶部工具条：媒体切换 + 排序/资源库/编辑/显示方式/标签筛选，单条可换行 */
/* 各控件内联成一条，空间不足时整体折行，避免每个控件单独占一行 */

.wl-badge {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: #ffb300;
  color: #111;
  font-size: 12px;
  font-weight: 700;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

/* 标签区域 */
/* 筛选入口：顶栏只保留这一个按钮，详细条件收进下方面板 */
.tags-section {
  margin-bottom: 16px;
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 12px 16px;
}

.tags-header {
  margin-bottom: 12px;
}

.tags-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

/* 标签树导航 */
.tag-tree-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.tag-breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}

.breadcrumb-root {
  color: var(--info);
  cursor: pointer;
}

.breadcrumb-root:hover {
  text-decoration: underline;
}

.breadcrumb-sep {
  color: var(--border-strong);
}

.breadcrumb-item {
  color: var(--text-secondary);
  cursor: pointer;
}

.breadcrumb-item:hover {
  color: var(--accent);
}

.breadcrumb-item.active {
  color: var(--info);
  cursor: default;
}

.nav-back-btn {
  background: var(--bg-surface-2);
  border: none;
  color: var(--text-secondary);
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav-back-btn:hover {
  background: var(--border-strong);
  color: var(--accent);
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 标签导航项 */
.tag-nav-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-default);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
}

.tag-nav-item:hover {
  background: var(--bg-surface-2);
  border-color: var(--border-strong);
}

.tag-nav-item.active {
  background: var(--accent);
  border-color: var(--accent);
}

.tag-nav-item.all-tag {
  background: var(--bg-surface-2);
}

/* 未标记（待整理）：灰色低调，与真实标签区分，不抢视觉 */
.tag-nav-item.untagged-tag {
  border-style: dashed;
  border-color: var(--border-default);
  color: var(--text-secondary);
}

.tag-nav-item.untagged-tag:hover {
  background: var(--bg-surface-hover);
  border-color: var(--border-strong);
  color: var(--text-secondary);
}

.tag-nav-item.untagged-tag.active {
  background: var(--warning-soft);
  border-color: #c79100;
  color: #ffca28;
}

.tag-nav-item.untagged-tag .tag-nav-name {
  color: inherit;
}

.untagged-badge {
  background: var(--bg-surface-hover);
  color: var(--text-tertiary);
}

.tag-nav-item.untagged-tag.active .untagged-badge {
  background: var(--warning-soft);
  color: #ffca28;
}

.tag-nav-name {
  font-size: 13px;
  color: var(--text-secondary);
}

.tag-nav-item.active .tag-nav-name {
  color: var(--text-primary);
}

.tag-nav-badge {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: var(--text-secondary);
  background: var(--bg-surface);
  padding: 2px 6px;
  border-radius: 10px;
}

.tag-nav-arrow {
  font-size: 12px;
  font-weight: bold;
}

.no-tags {
  color: var(--text-tertiary);
  font-size: 13px;
  text-align: center;
  padding: 12px;
  width: 100%;
}

/* 标签筛选折叠按钮 */
.tags-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  text-decoration: none;
  transition: all 0.2s;
}

.selected-tag-name {
  color: var(--accent);
  font-weight: 500;
}

/* 排序选择器 */
.sort-label {
  color: var(--text-secondary);
  font-size: 14px;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 加载中 */
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
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

/* 视频网格 */
.video-section {
  margin-bottom: 32px;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
  align-items: start; /* 不同宽高比的卡片顶部对齐，不互相拉伸 */
}

/* 显示模式切换 */

/* 列表模式 */
.video-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  color: var(--text-tertiary);
}

.empty-state p {
  margin-top: 16px;
  font-size: 16px;
}

/* 滚动自动加载提示 */
.loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 20px;
  color: var(--text-secondary);
}

.loading-more p {
  margin: 0;
  font-size: 14px;
}

.spinner-small {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border-default);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 分页组件 */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 0;
  flex-wrap: wrap;
}

/* 桌面端隐藏移动端悬浮翻页栏 */
.mobile-pager {
  display: none;
}

.page-btn {
  padding: 8px 14px;
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover);
  color: var(--accent);
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-btn.active {
  background: var(--accent);
  color: var(--text-on-accent);
  border-color: var(--accent);
}

.page-ellipsis {
  color: var(--text-tertiary);
  padding: 0 4px;
}

.page-info {
  color: var(--text-secondary);
  font-size: 13px;
  margin-left: 12px;
}

/* 继续观看 */
.continue-section {
  margin-bottom: 32px;
}
.continue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}
.continue-header:hover { background: var(--bg-surface-hover); }
.continue-header.expanded { border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
.continue-title-row { display: flex; align-items: center; gap: 8px; }
.continue-title-row .section-title { margin: 0; font-size: 17px; }
.continue-count {
  min-width: 20px;
  padding: 1px 7px;
  background: var(--accent);
  color: var(--text-on-accent);
  border-radius: 10px;
  font-size: 12px;
  text-align: center;
}
.chev { color: var(--text-secondary); transition: transform 0.2s ease; }
.chev.open { transform: rotate(90deg); }
.continue-hint { color: var(--text-secondary); font-size: 13px; }
.continue-more { margin: 10px 2px 0; color: var(--text-tertiary); font-size: 12px; }
.continue-section .video-grid { margin-top: 14px; }

.section-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 16px;
}

.continue-card {
  cursor: pointer;
  background: var(--bg-surface);
  border-radius: 12px;
  overflow: hidden;
  transition: transform 0.2s;
}

.continue-card:hover {
  transform: translateY(-4px);
}

.continue-thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  overflow: hidden;
}

.continue-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.continue-duration {
  position: absolute;
  bottom: 8px;
  right: 8px;
  padding: 2px 6px;
  background: rgba(0, 0, 0, 0.8);
  border-radius: 4px;
  font-size: 12px;
  color: var(--text-on-accent);
}

.continue-progress {
  position: absolute;
  left: 0;
  bottom: 0;
  width: 100%;
  height: 4px;
  background: rgba(0, 0, 0, 0.5);
}

.continue-progress-bar {
  height: 100%;
  background: var(--like);
}

.continue-info {
  padding: 10px 12px;
}

.continue-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0 0 4px;
  line-height: 1.4;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.continue-pct {
  font-size: 12px;
  color: var(--like);
}

/* 响应式 */
@media (max-width: 1400px) {
  .video-grid {
    grid-template-columns: repeat(4, 1fr);
  }
}

@media (max-width: 1100px) {
  .video-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 700px) {
  .video-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 移动端底部单手翻页栏：桌面默认隐藏，仅移动端（下方 @media）显示 */
.mobile-pager {
  display: none;
}

@media (max-width: 600px) {
  .home-container {
    padding: 12px;
    max-width: 100vw;
  }
  
  /* 移动端两列布局 */
  .video-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    width: 100%;
  }
  
  .section-title {
    font-size: 18px;
  }
  
  .tags-section {
    padding: 12px;
    max-width: 100%;
  }
  
  .tags-container {
    max-width: 100%;
  }
  
  /* 移动端：工具条整体占满宽度，控件自动换行，避免溢出又不再各自独占一行 */

  .sort-label {
    display: none;
  }

  /* 移动端：底部悬浮单手翻页栏 */
  .mobile-pager {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    position: fixed;
    left: 0; right: 0; bottom: 0;
    padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
    background: var(--nav-bg);
    backdrop-filter: saturate(180%) blur(20px);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    border-top: 1px solid var(--border-subtle);
    z-index: 50;
  }

  /* 移动端只保留底部悬浮的单手翻页，隐藏桌面分页，避免两个翻页器重叠 */
  .pagination { display: none; }

  .mobile-page-btn {
    flex: 1;
    height: 44px;
    border-radius: 22px;
    font-size: 14px;
  }

  .mobile-page-info {
    color: var(--text-secondary);
    font-size: 13px;
    white-space: nowrap;
  }

  /* 给底部悬浮翻页栏留出空间，避免遮挡最后一行 */
  .video-section {
    padding-bottom: 76px;
  }

  /* 移动端显示模式切换占满整行 */
  /* 移动端显示方式切换与控件同行，不再独占整行 */

  /* 移动端：标签筛选与"更多"均为内容宽度、与排序/显示方式同排，不独占整行 */
  .tags-toggle-btn {
    flex: 0 0 auto;
  }

  /* 移动端：筛选框与更多按钮同行，框内 tab 可横向滚动不挤占更多 */

  /* 移动端列表模式：缩略图收窄让位标题，操作按钮不再霸占右侧空间 */
  .video-list-row {
    gap: 10px;
    padding: 8px 10px;
    align-items: stretch;
  }

  .list-thumb {
    width: 92px;
    align-self: center;
  }

  /* 标题区占满缩略图到操作按钮之间的全部宽度 */
  .list-info {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }

  .list-title {
    font-size: 15px;
    line-height: 1.4;
    margin: 0 0 4px 0;
    white-space: normal;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    line-clamp: 2;
  }

  /* 手机端列表：普通模式下操作列不占位，标题占满；仅编辑模式显示编辑按钮 */
  .list-actions {
    display: none;
  }
  .list-actions:has(.list-action-btn) {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: auto;
    gap: 6px;
  }

  .list-action-btn {
    width: 30px;
    height: 30px;
  }

  /* 列表缩略图本就小，缩小右上角稍后再看浮层，避免喧宾夺主 */
  .list-thumb .watch-later-btn.overlay {
    width: 22px;
    height: 22px;
    top: 4px;
    right: 4px;
    opacity: 0.8;
    background: rgba(0, 0, 0, 0.35);
    backdrop-filter: blur(1px);
  }
  .list-thumb .watch-later-btn.overlay .wl-icon {
    width: 12px;
    height: 12px;
  }
}
</style>
