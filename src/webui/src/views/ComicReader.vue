<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import { useComicStore } from '../stores/comicStore'
import type { Comic } from '../types'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const comicStore = useComicStore()

const comic = ref<Comic | null>(null)
const loading = ref(true)
const error = ref('')

const mode = ref<'scroll' | 'page'>((localStorage.getItem('dplayer_comic_mode') as any) || 'scroll')
const fit = ref<'width' | 'height' | 'original'>((localStorage.getItem('dplayer_comic_fit') as any) || 'width')
const currentPage = ref(1)
const showThumbs = ref(false)

// 沉浸全屏阅读模式
const immersive = ref(localStorage.getItem('dplayer_comic_immersive') === '1')
const controlsVisible = ref(true) // 沉浸式下控件是否可见（点击屏幕切换）
const readerEl = ref<HTMLElement | null>(null)

const total = computed(() => comic.value?.page_count || 0)
const pages = computed(() => comic.value?.pages || [])

const withToken = (url: string) => (url && userStore.token) ? `${url}?token=${userStore.token}` : (url || '')

const scrollContainer = ref<HTMLElement | null>(null)

// 续读滚动定位相关
const resumePrefix = ref(0)       // 续读时前缀图片设为 eager 加载，保证布局高度正确
const pendingScroll = ref<number | null>(null)  // 待滚动定位的目标页（图片加载完成后执行）
const suppressScroll = ref(false) // 程序化滚动后短暂屏蔽 onScroll 的页码重算

// 滚动时自动隐藏工具栏（下滑隐藏 / 上滑显示，只留底部进度条）
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
  if (!comic.value) return
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = window.setTimeout(() => {
    comicStore.saveProgress(comic.value!.hash, currentPage.value, currentPage.value / total.value)
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
    // 滚动方向自动隐藏/显示工具栏：下滑隐藏（只留进度条），上滑显示
    if (!immersive.value && !suppressDir.value) {
      const top = container.scrollTop
      const d = top - lastScrollTop
      if (d > 6) uiHidden.value = true
      else if (d < -6) uiHidden.value = false
      lastScrollTop = top
    }
    const imgs = container.querySelectorAll('img.comic-page-img')
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
  const imgs = Array.from(container.querySelectorAll('img.comic-page-img'))
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
  }
}

const back = () => {
  if (window.history.length > 1) router.back()
  else router.push({ name: 'Comics' })
}

const setMode = (m: 'scroll' | 'page') => {
  mode.value = m
  localStorage.setItem('dplayer_comic_mode', m)
  if (m === 'scroll') nextTick(() => goToPage(currentPage.value))
}
const setFit = (f: 'width' | 'height' | 'original') => {
  fit.value = f
  localStorage.setItem('dplayer_comic_fit', f)
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
  uiHidden.value = false // 进出沉浸模式都复位工具栏显隐
  localStorage.setItem('dplayer_comic_immersive', v ? '1' : '0')
  document.body.classList.toggle('reader-immersive', v)
  if (v) {
    controlsVisible.value = true
    nextTick(enterFullscreen)
  } else {
    exitFullscreen()
  }
}
const toggleImmersive = () => setImmersive(!immersive.value)
// 沉浸式下点击阅读区切换控件显隐
const toggleControls = () => {
  if (immersive.value) controlsVisible.value = !controlsVisible.value
}

const interact = (type: 'like' | 'favorite' | 'dislike') => {
  if (!comic.value) return
  comicStore.interact(comic.value.hash, type)
}

// 当前页图片（page 模式仅渲染当前页）
const currentImage = computed(() => pages.value[currentPage.value - 1]?.url || '')

onMounted(async () => {
  const hash = route.params.hash as string
  try {
    const res: any = await (await import('../api')).comicApi.getComic(hash)
    if (res.success) {
      comic.value = res.comic
      const lp = res.comic.last_page || 1
      currentPage.value = clampPage(lp)
      await nextTick()
      if (mode.value === 'scroll' && lp > 1) {
        // 续读：先 eager 加载前缀图片（1..lp），待其全部加载完成后再精确滚动，
        // 否则图片未加载时高度未知，滚动位置会错位导致进度/页码错误。
        pendingScroll.value = lp
        resumePrefix.value = lp
        nextTick(() => waitAndScroll(lp))
      }
    } else {
      error.value = res.message || '加载失败'
    }
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
  window.addEventListener('keydown', onKey)
  document.addEventListener('fullscreenchange', onFullscreenChange)
  document.addEventListener('webkitfullscreenchange', onFullscreenChange)
})
onUnmounted(() => {
  window.removeEventListener('keydown', onKey)
  document.removeEventListener('fullscreenchange', onFullscreenChange)
  document.removeEventListener('webkitfullscreenchange', onFullscreenChange)
  document.body.classList.remove('reader-immersive')
  exitFullscreen()
  if (saveTimer) clearTimeout(saveTimer)
  // 离开时再保存一次进度
  if (comic.value) comicStore.saveProgress(comic.value.hash, currentPage.value, currentPage.value / total.value)
})

watch(showThumbs, () => { /* 控制缩略图条显隐 */ })
</script>

<template>
  <div
    class="reader"
    :class="{ immersive: immersive, 'controls-shown': immersive && controlsVisible }"
    ref="readerEl"
    v-if="comic"
  >
    <!-- 沉浸模式下常驻的退出按钮（避免用户被锁死） -->
    <button
      class="immersive-exit"
      v-if="immersive"
      @click="setImmersive(false)"
      title="退出全屏 (Esc)"
    >✕ 退出</button>

    <!-- 顶部工具栏 -->
    <div class="reader-bar" :class="{ 'ui-hidden': uiHidden }">
      <button class="bar-btn" @click="back" title="返回">‹ 返回</button>
      <div class="bar-title" :title="comic.title">{{ comic.title }}</div>
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
        <button class="bar-btn" :class="{active: comic.is_liked}" @click="interact('like')" title="点赞">♥</button>
        <button class="bar-btn" :class="{active: comic.is_favorited}" @click="interact('favorite')" title="收藏">★</button>
        <button class="bar-btn" :class="{active: comic.is_disliked}" @click="interact('dislike')" title="不喜欢">✕</button>
        <span class="divider"></span>
        <button class="bar-btn" :class="{active: mode==='scroll'}" @click="setMode('scroll')" title="滚动模式">滚动</button>
        <button class="bar-btn" :class="{active: mode==='page'}" @click="setMode('page')" title="翻页模式">翻页</button>
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
        <img :src="withToken(p.url)" loading="lazy" @error="(e:any)=>e.target.style.opacity=0.2" />
        <span class="thumb-idx">{{ p.index }}</span>
      </div>
    </div>

    <!-- 阅读区 -->
    <div class="reader-body" :class="mode" @click="toggleControls">
      <!-- 翻页模式：单页 -->
      <div v-if="mode==='page'" class="page-mode">
        <img
          class="comic-page-img"
          :data-page="currentPage"
          :style="imgStyle"
          :src="withToken(currentImage)"
          @load="updateProgress"
          @error="(e:any)=>e.target.src='/placeholder.jpg'"
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
          class="comic-page-img"
          :data-page="p.index"
          :style="imgStyle"
          :src="withToken(p.url)"
          :loading="p.index <= resumePrefix ? 'eager' : 'lazy'"
          @load="onImgLoad(p.index)"
          @error="(e:any)=>e.target.src='/placeholder.jpg'"
        />
      </div>
    </div>

    <!-- 底部进度条：常驻显示（正常/沉浸模式都可见），可点击跳转 -->
    <div class="reader-progress" v-if="comic">
      <span class="rp-text">{{ currentPage }} / {{ total }} · {{ progressPercent }}%</span>
      <div class="rp-track" @click="onSeek">
        <div class="rp-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
    </div>
  </div>

  <div class="reader-loading" v-else-if="loading">
    <div class="spinner"></div><p>加载中...</p>
  </div>
  <div class="reader-error" v-else>
    <p>{{ error || '加载失败' }}</p>
    <button class="bar-btn" @click="back">返回</button>
  </div>
</template>

<style scoped>
.reader { position: relative; height: calc(100vh - var(--nav-height, 60px)); display: flex; flex-direction: column; background: #0e0e0e; }
.reader-bar { display: flex; align-items: center; gap: 12px; padding: 8px 14px; background: #1a1a1a; border-bottom: 1px solid #2a2a2a; flex-wrap: wrap; transition: transform 0.25s ease, opacity 0.25s ease; }
.reader-bar.ui-hidden { transform: translateY(-110%); opacity: 0; pointer-events: none; }
.bar-btn { background: #2a2a2a; border: 1px solid #333; color: #ccc; border-radius: 6px; padding: 6px 12px; font-size: 13px; cursor: pointer; transition: all 0.2s; }
.bar-btn:hover:not(:disabled) { background: #333; color: #fff; }
.bar-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.bar-btn.active { background: #2196F3; color: #fff; border-color: #2196F3; }
.bar-title { font-size: 14px; font-weight: 500; color: #fff; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-page { display: flex; align-items: center; gap: 6px; }
.page-input { width: 56px; height: 32px; text-align: center; background: #1a1a1a; border: 1px solid #333; border-radius: 6px; color: #fff; font-size: 13px; }
.page-total { color: #999; font-size: 13px; }
.reader-progress { display: flex; align-items: center; gap: 10px; padding: 5px 14px; background: #161616; border-top: 1px solid #2a2a2a; }
.rp-text { color: #bbb; font-size: 12px; white-space: nowrap; }
.rp-track { flex: 1; height: 5px; background: #2a2a2a; border-radius: 3px; cursor: pointer; overflow: hidden; }
.rp-fill { height: 100%; background: #2196F3; transition: width 0.2s; }
.bar-tools { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.divider { width: 1px; height: 22px; background: #333; margin: 0 2px; }
.thumbs-strip { display: flex; gap: 6px; padding: 8px; background: #161616; border-bottom: 1px solid #2a2a2a; overflow-x: auto; max-height: 110px; transition: opacity 0.2s ease; }
.thumbs-strip.ui-hidden { display: none; }
.thumb-item { position: relative; flex-shrink: 0; width: 64px; height: 88px; border-radius: 4px; overflow: hidden; cursor: pointer; border: 2px solid transparent; background: #000; }
.thumb-item.active { border-color: #2196F3; }
.thumb-item img { width: 100%; height: 100%; object-fit: cover; }
.thumb-idx { position: absolute; bottom: 2px; right: 2px; background: rgba(0,0,0,0.7); color: #fff; font-size: 10px; padding: 0 4px; border-radius: 3px; }
.reader-body { flex: 1; overflow: hidden; position: relative; }
.scroll-mode { height: 100%; overflow-y: auto; padding: 12px 0; display: flex; flex-direction: column; gap: 8px; align-items: center; background: #0e0e0e; }
.page-mode { height: 100%; display: flex; align-items: center; justify-content: center; overflow: auto; background: #0e0e0e; position: relative; }
.comic-page-img { background: #000; }
.page-nav { position: absolute; top: 50%; transform: translateY(-50%); width: 48px; height: 96px; background: rgba(0,0,0,0.4); color: #fff; display: flex; align-items: center; justify-content: center; font-size: 36px; cursor: pointer; border-radius: 8px; user-select: none; }
.page-nav:hover { background: rgba(0,0,0,0.65); }
.page-nav.prev { left: 12px; }
.page-nav.next { right: 12px; }
.reader-loading, .reader-error { height: calc(100vh - var(--nav-height, 60px)); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; color: #888; }
.spinner { width: 48px; height: 48px; border: 3px solid #333; border-top-color: #2196F3; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ============ 沉浸全屏阅读模式 ============ */
/* 进入沉浸：占满整个视口（忽略全局导航高度），并隐藏顶栏/缩略图 */
.reader.immersive { height: 100vh; height: 100dvh; max-height: 100vh; width: 100%; }
.reader.immersive .reader-bar { display: none; }
.reader.immersive.controls-shown .reader-bar { display: flex; animation: slideDown 0.2s ease; }
.reader.immersive .thumbs-strip { display: none; }
.reader.immersive.controls-shown .thumbs-strip { display: flex; }
.reader.immersive .reader-bar {
  position: fixed; top: 0; left: 0; right: 0; z-index: 50;
  background: rgba(20,20,20,0.92); backdrop-filter: blur(6px);
}
.reader.immersive .reader-body { height: 100%; padding-top: 0; }
/* 沉浸模式：底部进度条常驻可见，半透明叠在图片上 */
.reader.immersive .reader-progress { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(20,20,20,0.85); border-top: none; z-index: 40; }
/* 点击图片区域光标提示 */
.reader.immersive .reader-body { cursor: none; }
.reader.immersive.controls-shown .reader-body { cursor: default; }

.immersive-exit {
  position: fixed; top: 12px; left: 12px; z-index: 60;
  background: rgba(0,0,0,0.6); color: #fff; border: 1px solid rgba(255,255,255,0.25);
  border-radius: 20px; padding: 6px 14px; font-size: 13px; cursor: pointer;
  display: flex; align-items: center; gap: 4px; transition: all 0.2s;
}
.immersive-exit:hover { background: rgba(0,0,0,0.85); }
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
