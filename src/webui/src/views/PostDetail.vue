<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { postApi } from '../api'
import { useWatchLaterStore } from '../stores/watchLaterStore'
import { useUserStore } from '../stores/userStore'
import { UserRole } from '../types'
import VideoPlayer from '../components/VideoPlayer.vue'

const route = useRoute()
const router = useRouter()
const watchLaterStore = useWatchLaterStore()
const userStore = useUserStore()

function withToken(url: string): string {
  if (!url) return url
  const token = userStore.token
  if (!token) return url
  return url + (url.includes('?') ? '&' : '?') + 'token=' + token
}

const post = ref<any>(null)
const loading = ref(false)
const error = ref('')

const POST_TOKEN_RE = /\[([^\]]*)\]\(res:(\d+):(link|embed)\)/g

function renderSegments(content: string, refs: any[]) {
  const segs: any[] = []
  if (!content) return segs
  const byId = new Map((refs || []).map(r => [r.resource_index_id, r]))
  let last = 0
  POST_TOKEN_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = POST_TOKEN_RE.exec(content))) {
    if (m.index > last) segs.push({ type: 'text', text: content.slice(last, m.index) })
    const rid = parseInt(m[2], 10)
    segs.push({ type: 'ref', label: m[1], mode: m[3], resource_index_id: rid, ref: byId.get(rid) || null })
    last = m.index + m[0].length
  }
  if (last < content.length) segs.push({ type: 'text', text: content.slice(last) })
  return segs
}

function tokenRefIds(content: string) {
  const s = new Set<number>()
  if (!content) return s
  POST_TOKEN_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = POST_TOKEN_RE.exec(content))) s.add(parseInt(m[2], 10))
  return s
}

function orphanRefs(p: any) {
  const ids = tokenRefIds(p.content || '')
  return (p.refs || []).filter((r: any) => !ids.has(r.resource_index_id))
}

function toMediaItem(refItem: any) {
  if (refItem.video) {
    const v = refItem.video
    // 优先用 ref 级别 cover_url（_ref_cover_url 已自动附加 ?post=1），
    // 确保 hidden 资源在帖子中可预览；video 实体的 thumbnail 作为最终回退
    const cover = refItem.cover_url || v.thumbnail || ''
    return { type: 'video', hash: v.hash, title: v.title, cover, duration: v.duration || 0, date: v.created_at }
  }
  if (refItem.gallery) {
    const c = refItem.gallery
    return { type: 'gallery', hash: c.hash, title: c.title, cover: (c as any).cover_url || '', pageCount: c.page_count || 0, date: c.created_at, images: (refItem.images || []) as string[] }
  }
  if (refItem.text) {
    return { type: 'text', hash: String(refItem.text.resource_index_id), title: refItem.text.presentation?.title || '文本', cover: refItem.text.presentation?.thumbnail || '' }
  }
  if (refItem.docUrl) {
    return { type: 'document', docUrl: refItem.docUrl, title: (refItem.presentation?.title) || '文档', caption: (refItem.presentation?.caption) || '' }
  }
  if (refItem.presentation) {
    const p = refItem.presentation
    // 帖子专属图集（仅 post 模式、未建 Gallery 实体）：直接内联渲染资源目录下的图片
    if (refItem.kind === 'gallery_folder' && refItem.images && refItem.images.length) {
      return {
        type: 'gallery_folder',
        resourceIndexId: refItem.resource_index_id,
        images: refItem.images,
        title: p.title || '图片',
        caption: p.caption || '',
        pageCount: refItem.images.length,
      }
    }
    const isVideo = refItem.kind === 'video_file'
    // presentation fallback: 优先用 presentation.thumbnail，回退到 ref 级别 cover_url
    const cover2 = (p as any).thumbnail || refItem.cover_url || ''
    return { type: isVideo ? 'video' : 'gallery', hash: String(refItem.resource_index_id), title: p.title || '未命名资源', cover: cover2, duration: isVideo ? (p.duration || 0) : 0, pageCount: isVideo ? 0 : (p.page_count || 0) }
  }
  return null
}

function openRefLink(r: any) {
  if (!r) return
  if (r.video) { router.push(`/video/${r.video.hash}?post=1`); return }
  if (r.gallery) { router.push(`/gallery/${r.gallery.hash}?post=1`); return }
  if (r.text) { router.push(`/text/${r.text.id}?post=1`); return }
}

function formatDate(s?: string) {
  if (!s) return ''
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN')
}

const id = Number(route.params.id)
const fetchPost = async () => {
  loading.value = true
  error.value = ''
  try {
    const res: any = await postApi.get(id)
    post.value = res
  } catch (e: any) {
    error.value = e?.message || '加载失败'
  } finally {
    loading.value = false
  }
}
onMounted(() => {
  // 帖子详情页不依赖首页的 mode 参数，进入时规范化 URL，
  // 去掉从首页视频流/帖子列表带入的 ?mode=video 等遗留参数，但保留用于 J/K 导航的 prev/next。
  const keep: Record<string, string> = {}
  if (route.query.prev) keep.prev = String(route.query.prev)
  if (route.query.next) keep.next = String(route.query.next)
  if (Object.keys(route.query).length > Object.keys(keep).length) {
    router.replace({ path: `/post/${route.params.id}`, query: keep })
  }
  fetchPost()
  window.addEventListener('keydown', onPostKey)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onPostKey)
})

const onPostKey = (e: KeyboardEvent) => {
  const target = e.target as HTMLElement
  if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.isContentEditable)) return
  const prevId = route.query.prev ? Number(route.query.prev) : 0
  const nextId = route.query.next ? Number(route.query.next) : 0
  if (e.key === 'j' || e.key === 'J') {
    if (nextId) router.push({ path: `/post/${nextId}`, query: { prev: String(prevId || id), next: String(nextId) } })
  } else if (e.key === 'k' || e.key === 'K') {
    if (prevId) router.push({ path: `/post/${prevId}`, query: { prev: String(prevId), next: String(id) } })
  }
}

// 帖子专属图集内联渲染 + 点击放大
const lightbox = ref<{ images: string[]; index: number } | null>(null)
function openLightbox(images: string[], index: number) { lightbox.value = { images, index } }
function closeLightbox() { lightbox.value = null }
function lightboxPrev() {
  if (lightbox.value) lightbox.value.index = (lightbox.value.index - 1 + lightbox.value.images.length) % lightbox.value.images.length
}
function lightboxNext() {
  if (lightbox.value) lightbox.value.index = (lightbox.value.index + 1) % lightbox.value.images.length
}

const renderedOrphans = computed(() => {
  if (!post.value) return []
  return orphanRefs(post.value).map((refItem: any) => ({ refItem, item: toMediaItem(refItem) }))
})

// 详情页统一媒体流：视频 + 图集图片，按出现顺序合并
// 视频为独立项（放大展示/内嵌播放）；图集展开为独立图片项（可网格/大图切换）
interface DetailMedia {
  kind: 'video' | 'image'
  src: string                 // 图片 URL 或视频封面（已带 token）
  videoHash?: string
  playUrl?: string            // 视频播放地址
}
const VIEW_MODE_KEY = 'post_detail_view_mode'
const viewMode = ref<'grid' | 'reader'>(
  (localStorage.getItem(VIEW_MODE_KEY) as 'grid' | 'reader') || 'grid'
)
function setViewMode(m: 'grid' | 'reader') {
  viewMode.value = m
  localStorage.setItem(VIEW_MODE_KEY, m)
}
const detailMedia = computed<DetailMedia[]>(() => {
  if (!post.value) return []
  const out: DetailMedia[] = []
  const seen = new Set<number>()

  const pushRef = (refItem: any) => {
    if (!refItem || seen.has(refItem.resource_index_id)) return
    seen.add(refItem.resource_index_id)
    const item = toMediaItem(refItem)
    if (!item) return

    // 视频：独立项
    if ((item as any).type === 'video' && refItem.video) {
      // 播放地址使用后端返回的 video.url（/api/videos/{id}/play），
      // 与 Video.vue 保持一致：拼 token + post=1
      const base = refItem.video.url || ''
      const token = userStore.token
      const playUrl = token
        ? `${base}?token=${token}&post=1`
        : `${base}${base.includes('?') ? '&' : '?'}post=1`
      out.push({
        kind: 'video',
        src: withToken((item as any).cover || ''),
        videoHash: refItem.video.hash,
        playUrl,
      })
      return
    }

    // 图集：展开图片
    const imgs = (item as any).images as string[] | undefined
    if (imgs && imgs.length) {
      for (const s of imgs) out.push({ kind: 'image', src: withToken(s) })
      return
    }
    if ((item as any).type === 'gallery' && (item as any).cover) {
      out.push({ kind: 'image', src: withToken((item as any).cover) })
    }
  }

  // 1. 正文内嵌 embed
  if (post.value.content && post.value.refs?.length) {
    const byId = new Map((post.value.refs || []).map((r: any) => [r.resource_index_id, r]))
    POST_TOKEN_RE.lastIndex = 0
    let m: RegExpExecArray | null
    while ((m = POST_TOKEN_RE.exec(post.value.content))) {
      if (m[3] === 'embed') pushRef(byId.get(parseInt(m[2], 10)))
    }
  }
  // 2. 孤立引用
  for (const r of orphanRefs(post.value)) pushRef(r)

  return out
})

// 详情页内嵌视频播放
const playingVideo = ref<{ playUrl: string; poster: string } | null>(null)
function openVideoPlayer(dm: DetailMedia) {
  if (dm.kind === 'video' && dm.playUrl) playingVideo.value = { playUrl: dm.playUrl, poster: dm.src }
}
function closeVideoPlayer() { playingVideo.value = null }

const isWatchLater = computed(() => !!post.value && watchLaterStore.has('post', String(post.value.id)))
const toggleWatchLater = () => {
  if (!post.value) return
  const id = String(post.value.id)
  watchLaterStore.toggle({ type: 'post', id, title: post.value.title || '' })
}

// 删除（仅作者或管理员，列表/卡片已不再提供删除入口）
const canManage = computed(() => {
  const u = userStore.user
  if (!u || !post.value) return false
  return u.role <= UserRole.ADMIN || u.id === post.value.owner_id
})

// 删除弹卡
const showDeleteCard = ref(false)
const deleting = ref(false)
const deleteResources = ref(false)
// 关联资源列表（用于勾选是否删除本体）
const deleteResourceIds = ref<number[]>([])

const associatedResources = computed(() => {
  if (!post.value) return []
  return (post.value.refs || []).map((r: any) => ({
    resource_index_id: r.resource_index_id,
    kind: r.kind,
    type: r.type,
    location: r.location,
    cover_url: r.cover_url,
    title: (r.video?.title) || (r.gallery?.title) || (r.presentation?.title) || (r.note) || r.location || '未命名资源',
  }))
})

function openDeleteCard() {
  if (!post.value) return
  deleteResources.value = false
  deleteResourceIds.value = []
  showDeleteCard.value = true
}
function closeDeleteCard() {
  if (deleting.value) return
  showDeleteCard.value = false
}
function toggleResource(id: number) {
  const i = deleteResourceIds.value.indexOf(id)
  if (i >= 0) deleteResourceIds.value.splice(i, 1)
  else deleteResourceIds.value.push(id)
}

const removePost = async () => {
  if (!post.value) return
  deleting.value = true
  try {
    const payload: any = { delete_resources: deleteResources.value }
    if (deleteResources.value && deleteResourceIds.value.length) {
      payload.resource_index_ids = deleteResourceIds.value
    }
    const res: any = await postApi.remove(post.value.id, payload)
    const n = res?.deleted_resources?.length || 0
    showDeleteCard.value = false
    if (n > 0) alert(`帖子已删除，并移除了 ${n} 个关联资源`)
    router.push('/?mode=mixed')
  } catch (e: any) {
    alert(e?.message || '删除失败')
  } finally {
    deleting.value = false
  }
}
</script>

<template>
  <div class="detail-container">
    <div class="detail-topbar">
      <button class="back-btn" @click="router.back()">← 返回</button>
      <button class="watchlater-detail-btn" :class="{ active: isWatchLater }" @click="toggleWatchLater">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </svg>
        <span>{{ isWatchLater ? '已加入稍后再看' : '稍后再看' }}</span>
      </button>
      <button v-if="canManage" class="delete-detail-btn" @click="openDeleteCard" title="删除帖子">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
        <span>删除</span>
      </button>
    </div>
    <div v-if="loading" class="loading-container"><div class="spinner"></div><p>加载中...</p></div>
    <div v-else-if="error" class="error-box">{{ error }}</div>
    <div v-else-if="post" class="detail-card">
      <h1 v-if="post.title" class="detail-title">{{ post.title }}</h1>
      <div class="detail-meta">发布于 {{ formatDate(post.created_at) }} · 更新于 {{ formatDate(post.updated_at) }}</div>

      <div class="detail-source" v-if="post.authorName || post.sourceUrl">
        <span class="src-label">来源：</span>
        <a v-if="post.authorName" class="src-author" :href="post.authorUrl" target="_blank" rel="noopener">{{ post.authorName }}</a>
        <span v-if="post.authorName && post.sourceUrl" class="src-sep">·</span>
        <a v-if="post.sourceUrl" class="src-link" :href="post.sourceUrl" target="_blank" rel="noopener">查看原帖</a>
      </div>

      <div v-if="post.content" class="detail-content">
        <template v-for="(seg, i) in renderSegments(post.content, post.refs)" :key="i">
          <template v-if="seg.type === 'text'">{{ seg.text }}</template>
          <a v-else class="ref-link" @click="openRefLink(seg.ref)">{{ seg.label }}</a>
        </template>
      </div>

      <!-- 统一媒体区：视频放大 + 图片，可切换网格/大图 -->
      <div v-if="detailMedia.length" class="detail-media">
        <div class="media-toolbar">
          <span class="media-count">{{ detailMedia.length }} 项媒体 · 视频 {{ detailMedia.filter(m => m.kind === 'video').length }}</span>
          <div class="view-toggle">
            <button :class="{ active: viewMode === 'grid' }" @click="setViewMode('grid')">网格</button>
            <button :class="{ active: viewMode === 'reader' }" @click="setViewMode('reader')">大图</button>
          </div>
        </div>

        <!-- 网格模式：放大版朋友圈网格 -->
        <div v-if="viewMode === 'grid'" class="detail-grid" :class="`g-${Math.min(detailMedia.length, 9) || 1}`">
          <template v-for="(dm, di) in detailMedia" :key="di">
            <a v-if="dm.kind === 'video'" class="grid-cell video-cell" @click="openVideoPlayer(dm)">
              <img :src="dm.src" class="grid-img" loading="lazy" />
              <span class="grid-play">▶</span>
            </a>
            <img v-else :src="dm.src" class="grid-img" loading="lazy"
              @click="openLightbox(detailMedia.filter(m => m.kind === 'image').map(m => m.src), detailMedia.slice(0, di).filter(m => m.kind === 'image').length)" />
          </template>
        </div>

        <!-- 大图模式：纵向满宽流式阅读 -->
        <div v-else class="detail-reader">
          <template v-for="(dm, di) in detailMedia" :key="di">
            <div v-if="dm.kind === 'video'" class="reader-video">
              <VideoPlayer :src="dm.playUrl" :poster="dm.src" />
            </div>
            <img v-else :src="dm.src" class="reader-img" loading="lazy"
              @click="openLightbox(detailMedia.filter(m => m.kind === 'image').map(m => m.src), detailMedia.slice(0, di).filter(m => m.kind === 'image').length)" />
          </template>
        </div>
      </div>
      <p v-if="!post.content && (!post.refs || !post.refs.length)" class="no-refs">（暂无内容）</p>
    </div>

    <!-- 删除确认弹卡 -->
    <div v-if="showDeleteCard" class="del-mask" @click.self="closeDeleteCard">
      <div class="del-card">
        <div class="del-card-head">
          <span class="del-icon">⚠️</span>
          <h3>删除帖子</h3>
        </div>
        <p class="del-warn">确定要删除该帖子吗？此操作进入回收站，可恢复。</p>

        <label class="del-check-row" :class="{ on: deleteResources }">
          <input type="checkbox" v-model="deleteResources" />
          <span class="del-check-text">
            <strong>同时删除关联资源本体</strong>
            <small>勾选后会移除该帖子独占、且未被其它帖子或媒体库使用的资源索引（磁盘文件仍保留）。被共享或仍在媒体库中的资源不会被删除。</small>
          </span>
        </label>

        <div v-if="deleteResources && associatedResources.length" class="del-res-list">
          <div v-for="r in associatedResources" :key="r.resource_index_id" class="del-res-item" @click="toggleResource(r.resource_index_id)">
            <input type="checkbox" :checked="deleteResourceIds.includes(r.resource_index_id)" @click.stop.prevent="toggleResource(r.resource_index_id)" />
            <img v-if="r.cover_url" :src="withToken(r.cover_url)" class="del-res-cover" />
            <div class="del-res-info">
              <div class="del-res-title">{{ r.title }}</div>
              <div class="del-res-kind">{{ r.type || r.kind }}</div>
            </div>
          </div>
        </div>
        <p v-else-if="deleteResources && !associatedResources.length" class="del-no-res">该帖子没有关联的资源。</p>

        <div class="del-actions">
          <button class="del-cancel" @click="closeDeleteCard" :disabled="deleting">取消</button>
          <button class="del-confirm" @click="removePost" :disabled="deleting">
            {{ deleting ? '正在删除…' : '确认删除' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="lightbox" class="lightbox" @click.self="closeLightbox">
      <button class="lightbox-nav lightbox-prev" @click="lightboxPrev">‹</button>
      <img class="lightbox-img" :src="lightbox.images[lightbox.index]" />
      <button class="lightbox-nav lightbox-next" @click="lightboxNext">›</button>
      <span class="lightbox-count">{{ lightbox.index + 1 }} / {{ lightbox.images.length }}</span>
      <button class="lightbox-close" @click="closeLightbox">×</button>
    </div>

    <!-- 详情页内嵌视频播放器（网格模式点击触发） -->
    <div v-if="playingVideo" class="video-modal" @click.self="closeVideoPlayer">
      <button class="video-close" @click="closeVideoPlayer">×</button>
      <VideoPlayer :src="playingVideo.playUrl" :poster="playingVideo.poster" :autoplay="true" />
    </div>
  </div>
</template>

<style scoped>
.detail-container { padding: 20px; max-width: 900px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.back-btn { background: var(--bg-surface-hover); border: 1px solid var(--border-default); color: var(--text-secondary); border-radius: 8px; padding: 8px 16px; cursor: pointer; font-size: 14px; }
.back-btn:hover { color: var(--accent); }
.detail-topbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.watchlater-detail-btn { display: inline-flex; align-items: center; gap: 6px; background: var(--bg-surface-hover); border: 1px solid var(--border-default); color: var(--text-secondary); border-radius: 8px; padding: 8px 14px; cursor: pointer; font-size: 14px; }
.watchlater-detail-btn:hover { color: var(--accent); background: var(--bg-surface-2); }
.watchlater-detail-btn.active { color: #ffb300; border-color: rgba(255,179,0,0.4); background: rgba(255,179,0,0.12); }
.delete-detail-btn { display: inline-flex; align-items: center; gap: 6px; border: 1px solid var(--danger-soft); background: var(--danger-soft); color: var(--danger); border-radius: 8px; padding: 8px 14px; cursor: pointer; font-size: 14px; }
.delete-detail-btn:hover { background: var(--danger-soft); color: var(--danger); }
.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 200px; color: var(--text-secondary); }
.spinner { width: 36px; height: 36px; border: 3px solid var(--border-default); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { color: var(--danger); padding: 12px; background: var(--danger-soft); border-radius: 8px; }
.detail-card { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 14px; padding: 24px; }
.detail-title { font-size: 24px; font-weight: 700; color: var(--text-primary); margin: 0 0 8px; }
.detail-meta { color: var(--text-secondary); font-size: 13px; margin-bottom: 16px; }
.detail-source { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; font-size: 13px; color: var(--text-tertiary); }
.src-label { color: var(--text-secondary); }
.src-author { color: var(--accent); text-decoration: none; font-weight: 600; }
.src-author:hover { color: #90caf9; text-decoration: underline; }
.src-sep { color: var(--border-strong); }
.src-link { color: var(--accent); text-decoration: none; }
.src-link:hover { color: #90caf9; text-decoration: underline; }
.detail-content { color: var(--text-secondary); font-size: 15px; line-height: 1.7; white-space: pre-wrap; margin-bottom: 4px; }
.no-refs { color: var(--text-tertiary); font-size: 13px; }

/* 统一媒体区 */
.detail-media { margin-top: 16px; }
.media-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
.media-count { font-size: 12px; color: var(--text-tertiary); }
.view-toggle { display: inline-flex; background: var(--bg-surface-hover); border-radius: 8px; padding: 2px; gap: 2px; }
.view-toggle button { border: none; background: transparent; color: var(--text-secondary); padding: 5px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
.view-toggle button.active { background: var(--accent); color: #fff; }

/* 网格模式（放大版朋友圈网格） */
.detail-grid { display: grid; gap: 8px; border-radius: 12px; overflow: hidden; width: fit-content; max-width: 760px; }
.grid-cell { position: relative; display: block; cursor: pointer; border-radius: 8px; overflow: hidden; }
.grid-img { display: block; object-fit: cover; background: var(--bg-surface-hover); border-radius: 8px; transition: opacity .15s; }
.grid-img:hover { opacity: .9; }
.detail-grid.g-1 { grid-template-columns: 1fr; }
.detail-grid.g-1 .grid-img { width: 420px; height: auto; aspect-ratio: 16/10; border-radius: 12px; }
.detail-grid.g-2 { grid-template-columns: repeat(2, 1fr); }
.detail-grid.g-2 .grid-img { width: 280px; height: 280px; }
.detail-grid.g-3 { grid-template-columns: repeat(3, 1fr); }
.detail-grid.g-3 .grid-img { width: 200px; height: 200px; }
.detail-grid.g-4 { grid-template-columns: repeat(2, 1fr); }
.detail-grid.g-4 .grid-img { width: 280px; height: 280px; }
.detail-grid.g-5, .detail-grid.g-6, .detail-grid.g-7, .detail-grid.g-8, .detail-grid.g-9 { grid-template-columns: repeat(3, 1fr); }
.detail-grid[class*="g-5"] .grid-img,
.detail-grid[class*="g-6"] .grid-img,
.detail-grid[class*="g-7"] .grid-img,
.detail-grid[class*="g-8"] .grid-img,
.detail-grid[class*="g-9"] .grid-img { width: 200px; height: 200px; }
.grid-play { position: absolute; inset: 0; margin: auto; width: 56px; height: 56px; border-radius: 50%; background: rgba(0,0,0,.5); color: #fff; font-size: 22px; display: flex; align-items: center; justify-content: center; pointer-events: none; }
.video-cell .grid-img { border: 2px solid rgba(255,255,255,.08); }

/* 大图模式（纵向流式阅读） */
.detail-reader { display: flex; flex-direction: column; gap: 12px; margin-top: 4px; }
.reader-img { width: 100%; max-width: 760px; border-radius: 8px; cursor: zoom-in; background: var(--bg-surface-hover); }
.reader-video { width: 100%; max-width: 760px; }
.doc-card { display: inline-flex; align-items: center; gap: 10px; padding: 12px 16px; background: var(--info-soft); border: 1px solid var(--bg-surface-2); border-radius: 10px; color: var(--text-secondary); text-decoration: none; cursor: pointer; max-width: 100%; }
.doc-card:hover { border-color: var(--accent); color: var(--accent); }
.doc-icon { font-size: 22px; }
.doc-name { font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px; }
.doc-dl { margin-left: auto; font-size: 12px; color: var(--accent); background: var(--info-soft); border-radius: 6px; padding: 3px 10px; }
.lightbox { position: fixed; inset: 0; background: rgba(0,0,0,.92); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.lightbox-img { max-width: 92vw; max-height: 92vh; object-fit: contain; border-radius: 6px; }
.lightbox-nav { position: absolute; top: 50%; transform: translateY(-50%); background: rgba(255,255,255,.12); border: none; color: var(--text-on-accent); font-size: 40px; width: 56px; height: 56px; border-radius: 50%; cursor: pointer; }
.lightbox-prev { left: 20px; }
.lightbox-next { right: 20px; }
.lightbox-close { position: absolute; top: 20px; right: 24px; background: none; border: none; color: var(--text-on-accent); font-size: 36px; cursor: pointer; }
.lightbox-count { position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); color: var(--text-secondary); font-size: 14px; background: rgba(0,0,0,.5); padding: 4px 12px; border-radius: 12px; }
.video-modal { position: fixed; inset: 0; background: rgba(0,0,0,.9); display: flex; align-items: center; justify-content: center; z-index: 1200; padding: 24px; }
.video-modal .video-player { max-width: 92vw; max-height: 88vh; border-radius: 10px; }
.video-close { position: absolute; top: 20px; right: 24px; width: 44px; height: 44px; border: none; border-radius: 50%; background: rgba(255,255,255,.12); color: #fff; font-size: 26px; cursor: pointer; }
.video-close:hover { background: rgba(255,255,255,.25); }
.del-mask { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; z-index: 1100; padding: 16px; }
.del-card { width: 100%; max-width: 440px; background: var(--bg-surface-hover); border: 1px solid var(--border-default); border-radius: 16px; padding: 22px; box-shadow: 0 12px 40px rgba(0,0,0,.5); }
.del-card-head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.del-card-head h3 { margin: 0; font-size: 18px; color: var(--text-primary); }
.del-icon { font-size: 22px; }
.del-warn { color: var(--text-secondary); font-size: 14px; line-height: 1.6; margin: 0 0 16px; }
.del-check-row { display: flex; gap: 10px; align-items: flex-start; padding: 12px; border: 1px solid var(--border-default); border-radius: 10px; cursor: pointer; background: var(--bg-surface-hover); transition: border-color .15s, background .15s; }
.del-check-row.on { border-color: rgba(255,179,0,.5); background: rgba(255,179,0,.08); }
.del-check-row input { margin-top: 3px; width: 16px; height: 16px; accent-color: #ffb300; }
.del-check-text { display: flex; flex-direction: column; gap: 4px; }
.del-check-text strong { color: var(--text-primary); font-size: 14px; }
.del-check-text small { color: var(--text-tertiary); font-size: 12px; line-height: 1.5; }
.del-res-list { margin-top: 14px; display: flex; flex-direction: column; gap: 8px; max-height: 240px; overflow-y: auto; }
.del-res-item { display: flex; align-items: center; gap: 10px; padding: 8px; border: 1px solid var(--border-default); border-radius: 10px; cursor: pointer; background: var(--bg-surface); transition: border-color .15s; }
.del-res-item:hover { border-color: var(--border-default); }
.del-res-item input { width: 16px; height: 16px; accent-color: #ffb300; }
.del-res-cover { width: 44px; height: 44px; object-fit: cover; border-radius: 8px; background: #000; flex-shrink: 0; }
.del-res-info { display: flex; flex-direction: column; gap: 2px; overflow: hidden; }
.del-res-title { color: var(--text-primary); font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.del-res-kind { color: var(--text-secondary); font-size: 11px; }
.del-no-res { color: var(--text-secondary); font-size: 13px; margin: 12px 0 0; }
.del-actions { display: flex; gap: 12px; margin-top: 20px; }
.del-cancel, .del-confirm { flex: 1; padding: 10px; border-radius: 10px; font-size: 14px; cursor: pointer; border: 1px solid transparent; }
.del-cancel { background: var(--bg-surface-hover); border-color: var(--border-default); color: var(--text-secondary); }
.del-cancel:hover { background: var(--bg-surface-2); color: var(--accent); }
.del-confirm { background: #b22; color: var(--text-on-accent); border-color: #d33; }
.del-confirm:hover { background: #d22; }
.del-confirm:disabled, .del-cancel:disabled { opacity: .55; cursor: not-allowed; }
</style>
