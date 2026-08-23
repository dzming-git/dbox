<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import { useGalleryStore } from '../stores/galleryStore'
import { useWatchLaterStore } from '../stores/watchLaterStore'
import CollectionPanel from '../components/CollectionPanel.vue'
import BaseModal from '../components/BaseModal.vue'
import { useToast } from '../composables/useToast'
import type { Gallery } from '../types'

const { toastMessage, showToastFlag, showToast } = useToast()

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const galleryStore = useGalleryStore()
const watchLaterStore = useWatchLaterStore()

const gallery = ref<Gallery | null>(null)
const loading = ref(true)
const error = ref('')

const mode = ref<'scroll' | 'page'>((localStorage.getItem('dbox_gallery_mode') as any) || 'scroll')
const fit = ref<'width' | 'height' | 'original'>((localStorage.getItem('dbox_gallery_fit') as any) || 'width')
const currentPage = ref(1)
const showThumbs = ref(false)
const isInContinue = ref(false)   // 是否已在「继续阅读」列表（用户主动加入）

// 沉浸全屏阅读模式
const immersive = ref(localStorage.getItem('dbox_gallery_immersive') === '1')
const controlsVisible = ref(true) // 沉浸式下控件是否可见（点击屏幕切换）
const readerEl = ref<HTMLElement | null>(null)

const pages = computed(() => gallery.value?.pages || [])
// 总页数以实际渲染的页面列表为准，page_count 仅在无页面列表时兜底：
// page_count 是库中冗余列，可能滞后于目录实际内容，若比实际页数大，
// 进度条/翻页/末页判断都会以为后面还有图片。
const total = computed(() => pages.value.length || gallery.value?.page_count || 0)

const withToken = (url: string) => {
  if (!url) return ''
  const sep = url.includes('?') ? '&' : '?'
  return userStore.token ? `${url}${sep}token=${userStore.token}` : url
}

// 缓存失效版本号：图集「重新加载」后 updated_at 变化，URL 随之变化，
// 浏览器才会重新拉取；否则 /resource-file/<rid>/<idx> 是稳定 URL，
// 修好磁盘图片后仍会命中旧的失败缓存。
const galleryVer = computed(() => {
  const t = gallery.value?.updated_at
  const ts = t ? Date.parse(t) : NaN
  return Number.isNaN(ts) ? '' : `v=${ts}`
})

// 页面图片 URL：优先走 /resource-file/<resource_id>/<idx>（用资源索引 id + 页码），
// 规避目录名含方括号等特殊字符时 /gallery-page/<path> 在 URL 路由中 404 的问题；
// 无 resource_id 时回退旧的 /gallery-page/<path>。
const pageImageUrl = (p: any) => {
  if (p && p.resource_id != null && p.index != null) {
    const q = [galleryVer.value, userStore.token ? `token=${userStore.token}` : '']
      .filter(Boolean).join('&')
    return `/resource-file/${p.resource_id}/${Math.max(0, p.index - 1)}` + (q ? `?${q}` : '')
  }
  return withToken(p?.url || '')
}

// 内联占位图（data URI），避免失败图片反复请求不存在的 /placeholder.jpg 造成高频请求
const PLACEHOLDER =
  'data:image/svg+xml;charset=utf-8,' +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' width='40' height='40'>" +
    "<rect width='100%' height='100%' fill='#2a2a2a'/>" +
    "<text x='50%' y='50%' fill='#666' font-size='10' text-anchor='middle' dominant-baseline='middle'>图</text>" +
    '</svg>'
  )

// 失败页统一用响应式集合记录，而不是直接改 DOM 的 class/src：
// 直接改 DOM 时 Vue 并不知情，同一个 img 元素被复用时（翻页模式只有一个 img、
// 「重新加载」图集后滚动模式的 img 也会复用），占位图和失败样式会一直残留，
// 后续正常的图也会跟着变成小占位块，磁盘上已经修好的图更是再不会显示。
const failedPages = ref<Set<number>>(new Set())
const onPageError = (idx: number) => {
  if (failedPages.value.has(idx)) return
  const s = new Set(failedPages.value)
  s.add(idx)
  failedPages.value = s
}

const scrollContainer = ref<HTMLElement | null>(null)

// 续读滚动定位相关
const resumePrefix = ref(0)       // 续读时前缀图片设为 eager 加载，保证布局高度正确
const pendingScroll = ref<number | null>(null)  // 待滚动定位的目标页（图片加载完成后执行）
const suppressScroll = ref(false) // 程序化滚动后短暂屏蔽 onScroll 的页码重算

// 顶部工具栏在滚动模式下：下滑自动收起（只留底部进度条），上滑再出现。
// 底部进度条始终常驻（fixed + visualViewport），不受此影响。
// lastScrollTop 同时用于翻页/续读时的页码计算基准。
const uiHidden = ref(false)
let lastScrollTop = 0
const suppressDir = ref(false) // 主动翻页/跳转时短暂屏蔽方向误判

// 图片适配样式
const imgStyle = computed(() => {
  if (fit.value === 'height') {
    return { maxHeight: 'calc(100vh - 130px)', width: 'auto', maxWidth: '100%', display: 'block', margin: '0 auto' }
  }
  if (fit.value === 'original') {
    return { width: 'auto', height: 'auto', maxWidth: '100%', display: 'block', margin: '0 auto' }
  }
  return { width: '100%', height: 'auto', display: 'block', margin: '0 auto' }
})

const progressPercent = computed(() => total.value ? Math.round((currentPage.value / total.value) * 100) : 0)

// ============ 进度保存（防抖） ============
let saveTimer: number | null = null
const updateProgress = () => {
  if (!gallery.value) return
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    galleryStore.saveProgress(gallery.value!.hash, currentPage.value, currentPage.value / total.value)
  }, 1200)
}

// ============ 翻页 / 跳转 ============
const clampPage = (n: number) => Math.min(Math.max(1, n), total.value || 1)

const goToPage = (n: number) => {
  currentPage.value = clampPage(n)
  uiHidden.value = false // 主动翻页/跳转时显示工具栏
  if (mode.value === 'scroll' && scrollContainer.value) {
    const el = scrollContainer.value.querySelector(`img[data-page="${currentPage.value}"]`) as HTMLElement | null
    if (el) {
      suppressDir.value = true // 屏蔽翻页滚动带来的方向误判
      setTimeout(() => { suppressDir.value = false }, 400)
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }
  updateProgress()
}

const next = () => goToPage(currentPage.value + 1)
const prev = () => goToPage(currentPage.value - 1)

// 点击底部进度条跳转到对应页
const onSeek = (e: MouseEvent) => {
  const el = e.currentTarget as HTMLElement
  const rect = el.getBoundingClientRect()
  const ratio = (e.clientX - rect.left) / rect.width
  goToPage(Math.max(1, Math.round(ratio * total.value)) || 1)
}

// 滚动模式：根据视口中心计算当前页
let scrollThrottle: number | null = null
const onScroll = () => {
  if (suppressScroll.value) return
  if (mode.value !== 'scroll' || !scrollContainer.value) return
  if (scrollThrottle) return
  scrollThrottle = window.setTimeout(() => {
    scrollThrottle = null
    const container = scrollContainer.value!
    // 滚动方向自动收起/显示顶部工具栏：下滑收起（只留底部进度条），上滑显示。
    // 非沉浸用 uiHidden（顶栏滑出并折叠占位），沉浸用 controlsVisible（顶栏隐藏、留出全屏）。
    if (!suppressDir.value) {
      const top = container.scrollTop
      const maxScroll = container.scrollHeight - container.clientHeight
      const atTop = top <= 2
      const atBottom = maxScroll - top <= 2
      // 内容不足以滚动（极短图集）时不做方向收起，避免顶部工具栏抖动
      const notScrollable = maxScroll <= 2
      const d = top - lastScrollTop
      if (notScrollable) {
        // 不可滚动：保持原状（不主动展开/收起）
      } else if (!atTop && !atBottom) {
        // 仅在页面中部滚动时根据方向收起；到达上/下边界时（易因回弹抖动）
        // 跳过切换，防止顶部窗口高频显示/隐藏
        // 注意：按需求菜单栏隐藏后不再自动展开，需用户点击「展开」按钮手动唤出，
        // 因此这里只处理“下滑隐藏”，上滑与边界均不自动显示。
        if (d > 6) {
          if (immersive.value) controlsVisible.value = false
          else uiHidden.value = true
        }
        // 上滑不再自动展开（由用户点击「展开」按钮唤出）
      } else {
        // 处于边界：保持原状，不自动展开，避免回弹造成的方向抖动
      }
      lastScrollTop = top
    }
    const imgs = container.querySelectorAll('img.gallery-page-img')
    let cur = 1
    const mid = window.innerHeight / 2
    imgs.forEach((img) => {
      const rect = (img as HTMLElement).getBoundingClientRect()
      if (rect.top <= mid) cur = parseInt((img as HTMLElement).dataset.page || '1')
    })
    if (cur !== currentPage.value) {
      currentPage.value = cur
      updateProgress()
    }
  }, 150)
}

// ============ 续读滚动定位（等图片加载完成再滚，避免错位） ============
const waitAndScroll = (idx: number) => {
  const container = scrollContainer.value
  if (!container) { pendingScroll.value = null; return }
  // 只有目标页及其之前的所有图片都加载完成（有了正确高度），滚动位置才准确
  const imgs = Array.from(container.querySelectorAll('img.gallery-page-img'))
    .filter(img => parseInt((img as HTMLElement).dataset.page || '0') <= idx)
  const allLoaded = imgs.length > 0 && imgs.every(img => {
    const im = img as HTMLImageElement
    return im.complete && im.naturalWidth > 0
  })
  if (allLoaded) {
    const el = container.querySelector(`img[data-page="${idx}"]`) as HTMLElement | null
    if (el) {
      el.scrollIntoView({ behavior: 'auto', block: 'start' })
      lastScrollTop = container.scrollTop // 记录基准，避免续读后首次滚动误判方向
      // 程序化滚动后短暂屏蔽 onScroll，避免把当前页误算成屏幕中部的页
      suppressScroll.value = true
      setTimeout(() => { suppressScroll.value = false }, 500)
    }
    pendingScroll.value = null
  } else {
    setTimeout(() => waitAndScroll(idx), 120)
  }
}

const onImgLoad = (idx: number) => {
  if (pendingScroll.value !== null && idx === pendingScroll.value) {
    waitAndScroll(idx)
  }
}

// ============ 键盘 ============
const onKey = (e: KeyboardEvent) => {
  const tag = (e.target as HTMLElement)?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA') return
  switch (e.key) {
    case 'ArrowRight':
    case 'd':
    case 'D':
      if (mode.value === 'page') next(); else goToPage(currentPage.value + 1); break
    case 'ArrowLeft':
    case 'a':
    case 'A':
      if (mode.value === 'page') prev(); else goToPage(currentPage.value - 1); break
    case 'ArrowDown':
      if (mode.value === 'page') next(); break
    case 'ArrowUp':
      if (mode.value === 'page') prev(); break
    case ' ':
      e.preventDefault()
      if (mode.value === 'page') next()
      else if (scrollContainer.value) scrollContainer.value.scrollBy({ top: window.innerHeight * 0.9, behavior: 'smooth' })
      break
    case 'Home':
      e.preventDefault(); goToPage(1); break
    case 'End':
      e.preventDefault(); goToPage(total.value); break
    case 'Escape':
      if (immersive.value) setImmersive(false); else back(); break
    case 'f':
    case 'F':
      toggleImmersive(); break
    case 'h':
    case 'H':
      toggleControls(); break
    case 'j':
    case 'J':
      if (nextItem.value) goCollectionItem(nextItem.value); break
    case 'k':
    case 'K':
      if (prevItem.value) goCollectionItem(prevItem.value); break
  }
}

const back = () => {
  // 记录刚看过的图集，返回列表后将其置顶到随机推荐的第一个
  if (route.params.hash) {
    try { sessionStorage.setItem('lastViewedGallery', route.params.hash as string) } catch {}
  }
  if (window.history.length > 1) router.back()
  else router.push({ name: 'Gallerys' })
}

const setMode = (m: 'scroll' | 'page') => {
  mode.value = m
  localStorage.setItem('dbox_gallery_mode', m)
  if (m === 'scroll') nextTick(() => goToPage(currentPage.value))
}
const setFit = (f: 'width' | 'height' | 'original') => {
  fit.value = f
  localStorage.setItem('dbox_gallery_fit', f)
}

// ============ 沉浸全屏阅读模式 ============
const enterFullscreen = () => {
  const el = readerEl.value
  if (!el) return
  const fn = (el as any).requestFullscreen || (el as any).webkitRequestFullscreen
  if (fn) { try { fn.call(el) } catch { /* 忽略不支持 */ } }
}
const exitFullscreen = () => {
  const doc = document as any
  if (doc.fullscreenElement || doc.webkitFullscreenElement) {
    const fn = doc.exitFullscreen || doc.webkitExitFullscreen
    if (fn) { try { fn.call(doc) } catch { /* 忽略 */ } }
  }
}
const onFullscreenChange = () => {
  const doc = document as any
  const fs = doc.fullscreenElement || doc.webkitFullscreenElement
  // 用户在全屏下按了 Esc 退出，同步关闭沉浸模式
  if (!fs && immersive.value) setImmersive(false)
}
const setImmersive = (v: boolean) => {
  immersive.value = v
  updateViewportInsets() // 进入/退出沉浸时可视区基准变化，立即重算安全偏移
  uiHidden.value = false // 进出沉浸模式都复位工具栏显隐
  localStorage.setItem('dbox_gallery_immersive', v ? '1' : '0')
  document.body.classList.toggle('reader-immersive', v)
  if (v) {
    controlsVisible.value = true
    nextTick(enterFullscreen)
  } else {
    exitFullscreen()
  }
}
const toggleImmersive = () => setImmersive(!immersive.value)
// 沉浸式下点击阅读区切换控件显隐；非沉浸下唤回被收起的顶部工具栏
const toggleControls = () => {
  if (immersive.value) controlsVisible.value = !controlsVisible.value
  else uiHidden.value = false
}

const interact = async (type: 'like' | 'favorite' | 'dislike') => {
  if (!gallery.value) return
  const res: any = await galleryStore.interact(gallery.value.hash, type)
  // store 只更新 galleries 数组中的副本，详情页本地对象需同步刷新
  if (res && res.success) {
    gallery.value = {
      ...gallery.value,
      is_liked: type === 'like' ? res.active : gallery.value.is_liked,
      is_favorited: type === 'favorite' ? res.active : gallery.value.is_favorited,
      is_disliked: type === 'dislike' ? res.active : gallery.value.is_disliked,
      like_count: type === 'like' ? res.like_count : gallery.value.like_count,
      favorite_count: type === 'favorite' ? res.favorite_count : gallery.value.favorite_count,
    }
    const verb =
      type === 'like' ? (res.active ? '已点赞' : '已取消点赞')
      : type === 'favorite' ? (res.active ? '已收藏' : '已取消收藏')
      : (res.active ? '已点踩' : '已取消点踩')
    showToast(verb)
  } else {
    showToast('操作失败，请重试')
  }
}

const isWatchLater = computed(() => !!gallery.value && watchLaterStore.has('gallery', gallery.value.hash))
const toggleWatchLater = () => {
  if (!gallery.value) return
  const hash = gallery.value.hash
  watchLaterStore.toggle({
    type: 'gallery',
    id: hash,
    title: gallery.value.title,
    thumbnail: gallery.value.cover_url,
  })
  showToast(watchLaterStore.has('gallery', hash) ? '已添加到稍后再看' : '已从稍后再看移除')
}

// 显式加入 / 移出「继续阅读」列表（用户主动选择，不自动按打开行为加入）
const toggleContinue = async () => {
  if (!gallery.value) return
  const add = !isInContinue.value
  try {
    const res: any = await (await import('../api')).galleryApi.setContinue(gallery.value.hash, add)
    if (res.success) {
      isInContinue.value = !!res.in_continue
    }
  } catch (e) {
    console.error('toggleContinue failed', e)
  }
}

// 资源所属权：管理员或上传本人可删除（对齐视频方案）
const isAdmin = computed(() => userStore.isAdmin)
const canManageGallery = computed(() => {
  if (isAdmin.value) return true
  const uid = userStore.user?.id
  return !!uid && gallery.value?.owner_id === uid
})

// 资源隐藏 / 显示切换（仅管理员）：隐藏后不出现在图集库列表，仅在帖子流可见
const togglingHidden = ref(false)
const isHidden = computed(() => !!gallery.value?.hidden)
async function toggleHidden() {
  if (!gallery.value || togglingHidden.value) return
  const rid = gallery.value.resource_index_id
  if (!rid) return
  togglingHidden.value = true
  try {
    const api = await import('../api')
    const res: any = await api.resourceApi.setHidden(rid, !isHidden.value)
    gallery.value = { ...gallery.value, hidden: res.hidden }
  } catch (e) {
    console.error('切换隐藏状态失败', e)
  } finally {
    togglingHidden.value = false
  }
}

// “更多”菜单（收起不常用的“不喜欢”）
const showMoreMenu = ref(false)

// 删除确认（对齐视频方案：二次确认 + 可选永久删除文件）
const showDeleteConfirm = ref(false)
const deleteFileOption = ref(false)
const confirmDelete = () => {
  deleteFileOption.value = false
  showDeleteConfirm.value = true
}

// 重新加载资源：从磁盘重新同步页面/封面（图片被替换/增删后强制刷新）
const reloading = ref(false)
const reloadResource = async () => {
  if (!gallery.value) return
  if (reloading.value) return
  reloading.value = true
  try {
    const api = await import('../api')
    const res: any = await api.galleryApi.reloadGallery(gallery.value.hash)
    if (res?.success || res?.data?.success) {
      // 重新拉取详情（新的 updated_at 会让图片 URL 版本号变化，浏览器拉取新图）
      await loadGallery(gallery.value.hash)
      showToast('图集资源已重新加载')
    } else {
      showToast((res?.message || res?.data?.message || '重新加载失败'))
    }
  } catch (e: any) {
    showToast('重新加载失败：' + (e?.message || e))
  } finally {
    reloading.value = false
  }
}
const handleDelete = async () => {
  if (!gallery.value) return
  try {
    const api = await import('../api')
    const res: any = await api.galleryApi.deleteGallery(gallery.value.hash, deleteFileOption.value)
    if (res?.data?.success || res?.success) {
      showDeleteConfirm.value = false
      showToast('已删除图集')
      // 立即从缓存列表移除，避免返回列表页时仍显示已删除项
      galleryStore.removeGallery(gallery.value.hash)
      // 返回首页的图集模式页（Home?mode=gallery），保留资源模式/排序等菜单栏
      router.push({ name: 'Home', query: { mode: 'gallery' } })
    } else {
      showToast('删除失败：' + (res?.message || res?.data?.message || '未知错误'))
    }
  } catch (e: any) {
    console.error('deleteGallery failed', e)
    showToast('删除失败：' + (e?.message || e))
  }
}

// 当前页图片（page 模式仅渲染当前页）
const currentImage = computed(() => pageImageUrl(pages.value[currentPage.value - 1]))

// 移动端浏览器地址栏/手势栏会动态显隐，固定定位的顶/底工具栏必须贴合“可视区域”
// 边缘而非布局视口，否则会被地址栏遮住。用 visualViewport 实时计算上/下安全偏移，
// 挂到根元素 CSS 变量（--vv-top / --vv-bottom）上，供 fixed 工具栏使用。
const updateViewportInsets = () => {
  const root = document.documentElement
  const vv = window.visualViewport
  if (!vv) {
    root.style.setProperty('--vv-top', '0px')
    root.style.setProperty('--vv-bottom', '0px')
    return
  }
  const top = Math.max(0, vv.offsetTop)
  const bottom = Math.max(0, window.innerHeight - vv.height - vv.offsetTop)
  root.style.setProperty('--vv-top', top + 'px')
  root.style.setProperty('--vv-bottom', bottom + 'px')
}

// —— 合集连播上下文（图集）——
const collectionId = ref<number | null>(null)
const collectionItems = ref<{ type: string; hash: string; title?: string }[]>([])
const collectionName = ref('')
const inCollection = computed(() => collectionId.value !== null && collectionItems.value.length > 0)
const currentIndex = computed(() =>
  collectionItems.value.findIndex(i => i.type === 'gallery' && i.hash === (route.params.hash as string))
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
    const api = await import('../api')
    const itemsRes = await (api.collectionSetApi.getItems(collectionId.value) as any)
    if (itemsRes?.success) {
      collectionItems.value = (itemsRes.items || []).map((it: any) => ({
        type: it.media?.type || it.item_type,
        hash: it.media?.hash || it.item_hash,
        title: it.media?.title,
      }))
    }
    const colRes = await (api.collectionSetApi.getCollection(collectionId.value) as any)
    if (colRes?.success) collectionName.value = colRes.collection.name
  } catch (e) {
    console.error(e)
  }
}
const goCollectionItem = (it: { type: string; hash: string }) => {
  const base = it.type === 'video' ? '/video/' : '/gallery/'
  router.push(`${base}${it.hash}?collection=${collectionId.value}`)
}

const loadGallery = async (hash: string) => {
  loading.value = true
  error.value = ''
  // 切换图集时先清空，避免复用组件时残留上一个图集的标题/内容（即使新链接不可见也绝不展示旧标题）
  gallery.value = null
  failedPages.value = new Set()  // 失败页标记随图集重置，重新加载后已修复的页要能重新显示
  try {
    const res: any = await (await import('../api')).galleryApi.getGallery(hash)
    if (res.success) {
      gallery.value = res.gallery
      isInContinue.value = !!(res.gallery && res.gallery.in_continue)
      const lp = res.gallery.last_page || 1
      currentPage.value = clampPage(lp)
      await nextTick()
      updateViewportInsets()
      if (mode.value === 'scroll' && lp > 1) {
        // 续读：先 eager 加载前缀图片（1..lp），待其全部加载完成后再精确滚动，
        // 否则图片未加载时高度未知，滚动位置会错位导致进度/页码错误。
        pendingScroll.value = lp
        resumePrefix.value = lp
        nextTick(() => waitAndScroll(lp))
      }
    } else {
      // 资源不可见（未激活库/无权）：不泄露任何名称或存在性，统一提示「不存在」
      if (res.code === 404 || res.code === '404') {
        error.value = '资源不存在'
      } else {
        error.value = res.message || '加载失败'
      }
      gallery.value = null
    }
  } catch (e: any) {
    error.value = '资源不存在'
    gallery.value = null
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await loadGallery(route.params.hash as string)
  await loadCollectionContext()
  window.visualViewport?.addEventListener('resize', updateViewportInsets)
  window.visualViewport?.addEventListener('scroll', updateViewportInsets)
  window.addEventListener('resize', updateViewportInsets)
  updateViewportInsets()
  window.addEventListener('keydown', onKey)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('webkitfullscreenchange', onFullscreenChange)
  // 进入阅读器：隐藏全局导航，避免其固定定位遮挡阅读器顶部工具栏
  document.body.classList.add('reader-active')
})

// 合集内“上一话/下一话”跳转时重载图集
watch(() => route.params.hash, async (h) => {
  if (h) {
    await loadGallery(h as string)
    await loadCollectionContext()
  }
})
onUnmounted(() => {
  window.visualViewport?.removeEventListener('resize', updateViewportInsets)
  window.visualViewport?.removeEventListener('scroll', updateViewportInsets)
  window.removeEventListener('resize', updateViewportInsets)
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
  document.body.classList.remove('reader-immersive')
  document.body.classList.remove('reader-active')
  exitFullscreen()
  if (saveTimer) clearTimeout(saveTimer)
  // 离开时再保存一次进度
  if (gallery.value) galleryStore.saveProgress(gallery.value.hash, currentPage.value, currentPage.value / total.value)
})

watch(showThumbs, () => { /* 控制缩略图条显隐 */ })
</script>

<template>
  <div
    class="reader"
    :class="{ immersive: immersive, 'controls-shown': immersive && controlsVisible }"
    ref="readerEl"
    v-if="gallery"
  >
    <!-- 沉浸模式下常驻的退出按钮（避免用户被锁死） -->
    <button
      class="immersive-exit"
      v-if="immersive"
      @click="setImmersive(false)"
      title="退出全屏 (Esc)"
    >✕ 退出</button>

    <!-- 菜单隐藏后露出的小展开按钮，点击唤出顶部菜单（沉浸与非沉浸模式均生效） -->
    <button
      class="immersive-expand"
      v-if="uiHidden || !controlsVisible"
      @click="toggleControls"
      title="展开菜单"
    >☰</button>

    <!-- 顶部工具栏 -->
    <div class="reader-bar" :class="{ 'ui-hidden': uiHidden }">
      <button class="bar-btn" @click="back" title="返回">‹ 返回</button>
      <div class="bar-title" :title="gallery.title">{{ gallery.title }}</div>
      <div class="bar-page">
        <button class="bar-btn" @click="prev" :disabled="currentPage<=1">‹</button>
        <input
          class="page-input"
          type="number" min="1" :max="total"
          v-model.number="currentPage"
          @change="goToPage(currentPage)"
        />
        <span class="page-total">/ {{ total }}</span>
        <button class="bar-btn" @click="next" :disabled="currentPage>=total">›</button>
      </div>
      <div class="bar-tools">
        <!-- 点赞 -->
        <button class="bar-action" :class="{active: gallery.is_liked}" @click="interact('like')" title="点赞">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>
          <span>点赞</span>
        </button>
        <!-- 收藏 -->
        <button class="bar-action" :class="{active: gallery.is_favorited}" @click="interact('favorite')" title="收藏">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 17.27L18.18 21l-1.64-7.03L22 9.24l-7.19-.61L12 2 9.19 8.63 2 9.24l5.46 4.73L5.82 21z"/></svg>
          <span>收藏</span>
        </button>
        <!-- 稍后再看 -->
        <button class="bar-action" :class="{active: isWatchLater}" @click="toggleWatchLater" title="稍后再看">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="9" />
            <path d="M12 7v5l3 2" />
          </svg>
          <span>稍后再看</span>
        </button>
        <!-- 加入 / 移出继续阅读（清晰文字标签） -->
        <button class="bar-action" :class="{active: isInContinue}" @click="toggleContinue" :title="isInContinue ? '已在继续阅读' : '加入继续阅读'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>
          <span>{{ isInContinue ? '已加入' : '加入继续' }}</span>
        </button>
        <!-- 合集 -->
        <CollectionPanel item-type="gallery" :item-hash="(gallery && gallery.hash) || (route.params.hash as string)" />
        <!-- 更多（“不喜欢”收进此处，与视频方案一致） -->
        <div class="more-wrap">
          <button class="bar-action" @click="showMoreMenu = !showMoreMenu" title="更多">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>
            <span>更多</span>
          </button>
          <div v-if="showMoreMenu" class="more-menu" @click.self="showMoreMenu = false">
            <button class="more-item" :class="{active: gallery.is_disliked}" @click="interact('dislike'); showMoreMenu = false">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/></svg>
              <span>{{ gallery.is_disliked ? '取消不喜欢' : '不喜欢' }}</span>
            </button>
          </div>
        </div>
        <span class="divider"></span>
        <!-- 删除（仅管理员 / 上传本人可见） -->
        <button v-if="canManageGallery" class="bar-action" :disabled="reloading" @click="reloadResource" :title="reloading ? '正在重新加载…' : '重新加载资源（图片被替换/增删后强制刷新）'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          <span>{{ reloading ? '加载中' : '重新加载' }}</span>
        </button>
        <button v-if="canManageGallery" class="bar-action danger" @click="confirmDelete" title="删除图集">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><line x1="10" y1="11" x2="10" y2="17"/><line x1="14" y1="11" x2="14" y2="17"/></svg>
          <span>删除</span>
        </button>
        <button v-if="isAdmin" class="bar-action" :class="{ active: isHidden }" :disabled="togglingHidden" @click="toggleHidden" :title="isHidden ? '资源已隐藏，点击使其在图集库显示' : '资源可见，点击隐藏（仅帖子流可见）'">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
          <span>{{ isHidden ? '已隐藏' : '显示中' }}</span>
        </button>
        <span class="divider"></span>
        <button class="bar-btn" :class="{active: mode==='scroll'}" @click="setMode('scroll')" title="滚动模式">滚动</button>
        <button class="bar-btn" :class="{active: mode==='page'}" @click="setMode('page')" title="翻页模式">翻页</button>
        <template v-if="inCollection">
          <span class="divider"></span>
          <span class="cn-reader-info">合集·{{ collectionName }} ({{ currentIndex >= 0 ? currentIndex + 1 : '?' }}/{{ collectionItems.length }})</span>
          <button class="bar-btn" :disabled="!prevItem" @click="prevItem && goCollectionItem(prevItem)">‹ 上一话</button>
          <button class="bar-btn" :disabled="!nextItem" @click="nextItem && goCollectionItem(nextItem)">下一话 ›</button>
        </template>
        <span class="divider"></span>
        <button class="bar-btn" :class="{active: fit==='width'}" @click="setFit('width')" title="适应宽度">宽</button>
        <button class="bar-btn" :class="{active: fit==='height'}" @click="setFit('height')" title="适应高度">高</button>
        <button class="bar-btn" :class="{active: fit==='original'}" @click="setFit('original')" title="原始大小">原</button>
        <span class="divider"></span>
        <button class="bar-btn" :class="{active: showThumbs}" @click="showThumbs = !showThumbs" title="目录/缩略图">目录</button>
        <span class="divider"></span>
        <button class="bar-btn" :class="{active: immersive}" @click="toggleImmersive" :title="immersive ? '退出全屏 (F)' : '全屏沉浸阅读 (F)'">{{ immersive ? '退出全屏' : '全屏' }}</button>
      </div>
    </div>

    <!-- 缩略图条 -->
    <div class="thumbs-strip" v-if="showThumbs" :class="{ 'ui-hidden': uiHidden }">
      <div
        v-for="p in pages" :key="p.index"
        class="thumb-item"
        :class="{ active: p.index === currentPage }"
        @click="goToPage(p.index)"
      >
        <img
          :class="{ 'img-error': failedPages.has(p.index) }"
          :src="failedPages.has(p.index) ? PLACEHOLDER : pageImageUrl(p)"
          loading="lazy"
          @error="onPageError(p.index)"
        />
        <span class="thumb-idx">{{ p.index }}</span>
      </div>
    </div>

    <!-- 阅读区 -->
    <div class="reader-body" :class="mode" @click="toggleControls">
      <!-- 翻页模式：单页 -->
      <div v-if="mode==='page'" class="page-mode">
        <img
          class="gallery-page-img"
          :class="{ 'img-error': failedPages.has(currentPage) }"
          :data-page="currentPage"
          :style="imgStyle"
          :src="failedPages.has(currentPage) ? PLACEHOLDER : currentImage"
          @load="updateProgress"
          @error="onPageError(currentPage)"
        />
        <div class="page-nav prev" @click.stop="prev" v-if="currentPage>1">‹</div>
        <div class="page-nav next" @click.stop="next" v-if="currentPage<total">›</div>
      </div>

      <!-- 滚动模式：全部页堆叠 -->
      <div
        v-else
        class="scroll-mode"
        ref="scrollContainer"
        @scroll="onScroll"
      >
        <img
          v-for="p in pages"
          :key="p.index"
          class="gallery-page-img"
          :class="{ 'img-error': failedPages.has(p.index) }"
          :data-page="p.index"
          :style="imgStyle"
          :src="failedPages.has(p.index) ? PLACEHOLDER : pageImageUrl(p)"
          :loading="p.index <= resumePrefix ? 'eager' : 'lazy'"
          @load="onImgLoad(p.index)"
          @error="onPageError(p.index)"
        />
      </div>
    </div>

    <!-- 底部进度条：常驻显示（正常/沉浸模式都可见），可点击跳转 -->
    <div class="reader-progress" v-if="gallery">
      <span class="rp-text">{{ currentPage }} / {{ total }} · {{ progressPercent }}%</span>
      <div class="rp-track" @click="onSeek">
        <div class="rp-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
    </div>

    <!-- 删除确认对话框 -->
    <BaseModal v-model:visible="showDeleteConfirm" title="删除图集" max-width="440px">
      <p>确定将图集「{{ gallery?.title }}」移入回收站吗？管理员可在回收站中恢复或彻底删除。</p>
      <label class="delete-file-option">
        <input type="checkbox" v-model="deleteFileOption" />
        永久删除（不可恢复，将同时删除文件）
      </label>
      <template #footer>
        <button class="btn-secondary" @click="showDeleteConfirm = false">取消</button>
        <button class="btn-danger" @click="handleDelete">删除</button>
      </template>
    </BaseModal>
  </div>

  <!-- 加载中 / 加载失败：必须与上面的 .reader(v-if="gallery") 构成同一条
       v-if / v-else-if / v-else 链，中间不能插入其它元素（如 Toast），
       否则链会从插入的元素重新开始：图集加载成功后 v-else 依然成立，
       页面底部会常驻一屏「加载失败」占位，滚到最后一张再下滑就像“还有一张加载失败的图”，
       回滑时又会盖住正常图片。Toast 已移到分支之后独立渲染。 -->
  <div class="reader-loading" v-else-if="loading">
    <div class="spinner"></div><p>加载中...</p>
  </div>
  <div class="reader-error" v-else>
    <p>{{ error || '加载失败' }}</p>
    <button class="bar-btn" @click="back">返回</button>
  </div>

  <!-- Toast 提示（独立于上面的分支，自身 fixed 定位，不参与分支链） -->
  <div v-if="showToastFlag" class="toast" data-testid="gallery-toast">
    {{ toastMessage }}
  </div>
</template>

<style scoped>
/* Toast 提示 */
.toast {
  position: fixed;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.85);
  color: var(--text-on-accent);
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  z-index: 9999;
  pointer-events: none;
  max-width: 80vw;
  text-align: center;
}
.reader { position: relative; height: 100vh; height: 100dvh; display: flex; flex-direction: column; background: var(--bg-surface); }
.reader-bar { display: flex; align-items: center; gap: 12px; padding: 8px 14px; background: var(--bg-surface); border-bottom: 1px solid #2a2a2a; flex-wrap: wrap; overflow: visible; max-height: 400px; transition: transform 0.25s ease, opacity 0.25s ease, max-height 0.25s ease, padding 0.25s ease, border-width 0.25s ease; }
.reader-bar.ui-hidden { transform: translateY(-110%); opacity: 0; pointer-events: none; max-height: 0; padding-top: 0; padding-bottom: 0; border-bottom-width: 0; }
.bar-btn { background: var(--bg-surface-hover); border: 1px solid var(--border-default); color: var(--text-secondary); border-radius: 6px; padding: 6px 12px; font-size: 13px; cursor: pointer; transition: all 0.2s; }
.bar-btn:hover:not(:disabled) { background: #333; color: var(--text-on-accent); }
.bar-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.bar-btn.active { background: var(--accent); color: var(--text-on-accent); border-color: var(--accent); }
.bar-title { font-size: 14px; font-weight: 500; color: var(--text-primary); max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-page { display: flex; align-items: center; gap: 6px; }
.page-input { width: 56px; height: 32px; text-align: center; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-primary); font-size: 13px; }
.page-total { color: var(--text-tertiary); font-size: 13px; }
.reader-progress { position: fixed; left: 0; right: 0; bottom: var(--vv-bottom, 0px); z-index: 30; display: flex; align-items: center; gap: 10px; padding: 7px 14px; padding-bottom: calc(7px + env(safe-area-inset-bottom, 0px)); background: var(--bg-surface); border-top: 1px solid #2a2a2a; }
.rp-text { color: #bbb; font-size: 12px; white-space: nowrap; }
.rp-track { flex: 1; height: 5px; background: var(--bg-surface-hover); border-radius: 3px; cursor: pointer; overflow: hidden; }
.rp-fill { height: 100%; background: var(--accent); transition: width 0.2s; }
.bar-tools { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.divider { width: 1px; height: 22px; background: #333; margin: 0 2px; }
.cn-reader-info { font-size: 12px; color: var(--text-secondary); margin: 0 4px; white-space: nowrap; }
.thumbs-strip { display: flex; gap: 6px; padding: 8px; background: var(--bg-surface); border-bottom: 1px solid #2a2a2a; overflow-x: auto; max-height: 110px; transition: opacity 0.2s ease; }
.thumbs-strip.ui-hidden { display: none; }
.thumb-item { position: relative; flex-shrink: 0; width: 64px; height: 88px; border-radius: 4px; overflow: hidden; cursor: pointer; border: 2px solid transparent; background: #000; }
.thumb-item.active { border-color: var(--accent); }
.thumb-item img { width: 100%; height: 100%; object-fit: cover; }
.thumb-idx { position: absolute; bottom: 2px; right: 2px; background: rgba(0,0,0,0.7); color: var(--text-on-accent); font-size: 10px; padding: 0 4px; border-radius: 3px; }
.reader-body { flex: 1; min-height: 0; overflow: hidden; position: relative; padding-bottom: 44px; }
/* overscroll-behavior: contain —— 滚到最后一张再继续下滑时，不把滚动传递给外层文档，
   避免页面整体被拖动、把阅读区之外的内容拉进视口造成“后面还有一张”的错觉。 */
.scroll-mode { height: 100%; overflow-y: auto; overscroll-behavior-y: contain; padding: 12px 0; display: flex; flex-direction: column; gap: 8px; align-items: center; background: var(--bg-surface); }
.page-mode { height: 100%; display: flex; align-items: center; justify-content: center; overflow: auto; background: var(--bg-surface); position: relative; }
.gallery-page-img { background: #000; }
/* 加载失败的图片：固定小高度、不拉伸，避免被 width:100% 撑成占据整屏的“幽灵块”
   （否则滚动到底会误以为还有一张图，且回滑时该块会遮挡其它图片） */
.gallery-page-img.img-error {
  width: auto !important;
  max-width: 60%;
  height: 60px !important;
  object-fit: contain;
  opacity: 0.35;
  margin: 4px 0;
}
.thumb-item img.img-error { object-fit: contain; opacity: 0.3; }
.page-nav { position: absolute; top: 50%; transform: translateY(-50%); width: 48px; height: 96px; background: rgba(0,0,0,0.4); color: var(--text-on-accent); display: flex; align-items: center; justify-content: center; font-size: 36px; cursor: pointer; border-radius: 8px; user-select: none; }
.page-nav:hover { background: rgba(0,0,0,0.65); }
.page-nav.prev { left: 12px; }
.page-nav.next { right: 12px; }
.reader-loading, .reader-error { height: 100vh; height: 100dvh; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; color: var(--text-secondary); }
.spinner { width: 48px; height: 48px; border: 3px solid var(--border-default); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ============ 沉浸全屏阅读模式 ============ */
/* 进入沉浸：占满整个视口（忽略全局导航高度），并隐藏顶栏/缩略图 */
.reader.immersive { height: 100vh; height: 100dvh; max-height: 100dvh; width: 100%; }
.reader.immersive .reader-bar { display: none; }
.reader.immersive.controls-shown .reader-bar { display: flex; animation: slideDown 0.2s ease; }
.reader.immersive .thumbs-strip { display: none; }
.reader.immersive.controls-shown .thumbs-strip { display: flex; }
.reader.immersive .reader-bar {
  position: fixed; top: var(--vv-top, 0px); left: 0; right: 0; z-index: 50;
  background: rgba(20,20,20,0.92); backdrop-filter: blur(6px);
}
.reader.immersive .reader-body { height: 100%; padding-top: 0; }
/* 沉浸模式：底部进度条常驻可见，半透明叠在图片上 */
.reader.immersive .reader-progress { position: fixed; bottom: var(--vv-bottom, 0px); left: 0; right: 0; background: rgba(20,20,20,0.85); border-top: none; z-index: 40; }
/* 点击图片区域光标提示 */
.reader.immersive .reader-body { cursor: none; }
.reader.immersive.controls-shown .reader-body { cursor: default; }

.immersive-exit {
  position: fixed; top: 12px; left: 12px; z-index: 60;
  background: rgba(0,0,0,0.6); color: var(--text-on-accent); border: 1px solid rgba(255,255,255,0.25);
  border-radius: 20px; padding: 6px 14px; font-size: 13px; cursor: pointer;
  display: flex; align-items: center; gap: 4px; transition: all 0.2s;
}
.immersive-exit:hover { background: rgba(0,0,0,0.85); }

/* 菜单隐藏后露出的小展开按钮：尽量小，避免遮挡阅读内容 */
.immersive-expand {
  position: fixed; top: 12px; left: 12px; z-index: 60;
  width: 30px; height: 30px; line-height: 28px; text-align: center;
  background: rgba(0,0,0,0.5); color: var(--text-on-accent); border: 1px solid rgba(255,255,255,0.2);
  border-radius: 8px; font-size: 16px; cursor: pointer; padding: 0;
  transition: all 0.2s;
}
.immersive-expand:hover { background: rgba(0,0,0,0.8); }

/* 操作台：带文字标签的按钮（与视频详情页操作栏风格一致） */
.bar-action { display: inline-flex; align-items: center; gap: 5px; background: var(--bg-surface-hover); border: 1px solid var(--border-default); color: var(--text-secondary); border-radius: 6px; padding: 6px 12px; font-size: 13px; cursor: pointer; transition: all 0.2s; white-space: nowrap; }
.bar-action:hover:not(:disabled) { background: #333; color: var(--text-on-accent); }
.bar-action.active { background: var(--accent); color: var(--text-on-accent); border-color: var(--accent); }
.bar-action.danger { color: #ff8585; border-color: #5a2a2a; }
.bar-action.danger:hover { background: var(--danger-soft); color: var(--danger); }

/* 更多菜单（收起不常用的“不喜欢”） */
.more-wrap { position: relative; display: inline-flex; }
.more-menu { position: absolute; top: calc(100% + 8px); right: 0; z-index: 60; background: var(--bg-surface-hover); border: 1px solid var(--border-default); border-radius: 10px; padding: 6px; min-width: 150px; box-shadow: 0 12px 32px rgba(0,0,0,0.5); }
.more-item { display: flex; align-items: center; gap: 8px; width: 100%; padding: 9px 12px; background: transparent; border: none; color: #ddd; cursor: pointer; font-size: 13px; border-radius: 6px; text-align: left; }
.more-item:hover { background: #333; color: var(--text-on-accent); }
.more-item.active { color: #ffd93d; }

/* 删除确认对话框 */
.dialog p { color: #bbb; font-size: 14px; line-height: 1.6; margin: 0; }
.delete-file-option { display: flex; align-items: center; gap: 8px; margin-top: 14px; color: #aaa; font-size: 13px; cursor: pointer; }
.delete-file-option input { width: 16px; height: 16px; accent-color: #e53935; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
.btn-secondary { background: var(--bg-surface-hover); border: 1px solid #444; color: var(--text-secondary); padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.btn-secondary:hover { background: #333; color: var(--text-on-accent); }
.btn-danger { background: #e53935; border: 1px solid #e53935; color: var(--text-on-accent); padding: 8px 16px; border-radius: 8px; cursor: pointer; font-size: 14px; }
.btn-danger:hover { background: #f44336; }
.reader.immersive.controls-shown .immersive-exit { top: 64px; }

@keyframes slideDown { from { transform: translateY(-100%); } to { transform: translateY(0); } }

@media (max-width: 600px) {
  /* 移动端工具栏本身较占空间，进入沉浸后同样隐藏，点击唤出 */
  .reader.immersive .reader-bar {
    flex-wrap: wrap; gap: 6px; padding: 8px 10px;
  }
}
@media (max-width: 600px) {
  .bar-title { max-width: 120px; }
  .bar-tools { gap: 4px; }
  .bar-btn { padding: 5px 9px; font-size: 12px; }
}
</style>
