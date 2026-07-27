<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { postApi } from '../api'
import { useWatchLaterStore } from '../stores/watchLaterStore'
import { useUserStore } from '../stores/userStore'
import MediaCard from '../components/MediaCard.vue'

const route = useRoute()
const router = useRouter()
const watchLaterStore = useWatchLaterStore()
const userStore = useUserStore()

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
    return { type: 'video', hash: v.hash, title: v.title, cover: v.thumbnail || '', duration: v.duration || 0, date: v.created_at }
  }
  if (refItem.gallery) {
    const c = refItem.gallery
    return { type: 'gallery', hash: c.hash, title: c.title, cover: (c as any).cover_url || '', pageCount: c.page_count || 0, date: c.created_at }
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
    return { type: isVideo ? 'video' : 'gallery', hash: String(refItem.resource_index_id), title: p.title || '未命名资源', cover: p.thumbnail || '', duration: isVideo ? (p.duration || 0) : 0, pageCount: isVideo ? 0 : (p.page_count || 0) }
  }
  return null
}

function mediaTypeOf(refItem: any) {
  const it = toMediaItem(refItem)
  return it ? it.type : ''
}

function openRefLink(r: any) {
  if (!r) return
  if (r.video) { router.push(`/video/${r.video.hash}`); return }
  if (r.gallery) { router.push(`/gallery/${r.gallery.hash}`); return }
  if (r.text) { router.push(`/text/${r.text.id}`); return }
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
onMounted(fetchPost)

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

const isWatchLater = computed(() => !!post.value && watchLaterStore.has('post', String(post.value.id)))
const toggleWatchLater = () => {
  if (!post.value) return
  const id = String(post.value.id)
  watchLaterStore.toggle({ type: 'post', id, title: post.value.title || '未命名帖子' })
}

// 删除（仅作者或管理员，列表/卡片已不再提供删除入口）
const canManage = computed(() => {
  const u = userStore.user
  if (!u || !post.value) return false
  return u.role >= 2 || u.id === post.value.owner_id
})
const removePost = async () => {
  if (!post.value) return
  if (!confirm('确定删除该帖子？此操作不可恢复。')) return
  try {
    await postApi.remove(post.value.id)
    router.push('/?mode=mixed')
  } catch (e: any) {
    alert(e?.message || '删除失败')
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
      <button v-if="canManage" class="delete-detail-btn" @click="removePost" title="删除帖子">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
        <span>删除</span>
      </button>
    </div>
    <div v-if="loading" class="loading-container"><div class="spinner"></div><p>加载中...</p></div>
    <div v-else-if="error" class="error-box">{{ error }}</div>
    <div v-else-if="post" class="detail-card">
      <h1 class="detail-title">{{ post.title || '未命名帖子' }}</h1>
      <div class="detail-meta">发布于 {{ formatDate(post.created_at) }} · 更新于 {{ formatDate(post.updated_at) }}</div>

      <div v-if="post.content" class="detail-content">
        <template v-for="(seg, i) in renderSegments(post.content, post.refs)" :key="i">
          <template v-if="seg.type === 'text'">{{ seg.text }}</template>
          <span v-else class="inline-ref">
            <a class="ref-link" @click="openRefLink(seg.ref)">{{ seg.label }}</a>
            <template v-if="mediaTypeOf(seg.ref) === 'gallery_folder'">
              <div class="inline-gallery">
                <img v-for="(src, gi) in (toMediaItem(seg.ref) as any).images" :key="gi" :src="src" class="inline-gallery-img" loading="lazy" @click="openLightbox((toMediaItem(seg.ref) as any).images, gi)" />
              </div>
            </template>
            <a v-else-if="mediaTypeOf(seg.ref) === 'document'" class="doc-card" :href="(toMediaItem(seg.ref) as any).docUrl" target="_blank" download>
              <span class="doc-icon">📄</span>
              <span class="doc-name">{{ (toMediaItem(seg.ref) as any).title }}</span>
              <span class="doc-dl">下载</span>
            </a>
            <MediaCard v-else-if="seg.ref && seg.mode === 'embed'" :item="toMediaItem(seg.ref)" @click="openRefLink(seg.ref)" />
          </span>
        </template>
      </div>

      <div v-if="renderedOrphans.length" class="detail-refs">
        <div v-for="(ro, i) in renderedOrphans" :key="ro.refItem.ref_id || i" class="ref-block">
          <div v-if="ro.refItem.note" class="ref-note">{{ ro.refItem.note }}</div>
          <template v-if="ro.item && ro.item.type === 'gallery_folder'">
            <div class="inline-gallery">
              <img v-for="(src, gi) in ro.item.images" :key="gi" :src="src" class="inline-gallery-img" loading="lazy" @click="openLightbox(ro.item.images, gi)" />
            </div>
          </template>
          <a v-else-if="ro.item && ro.item.type === 'document'" class="doc-card" :href="ro.item.docUrl" target="_blank" download>
            <span class="doc-icon">📄</span>
            <span class="doc-name">{{ ro.item.title }}</span>
            <span class="doc-dl">下载</span>
          </a>
          <MediaCard v-else-if="ro.item" :item="ro.item" @click="openRefLink(ro.refItem)" />
        </div>
      </div>
      <p v-if="!post.content && (!post.refs || !post.refs.length)" class="no-refs">（暂无内容）</p>
    </div>

    <div v-if="lightbox" class="lightbox" @click.self="closeLightbox">
      <button class="lightbox-nav lightbox-prev" @click="lightboxPrev">‹</button>
      <img class="lightbox-img" :src="lightbox.images[lightbox.index]" />
      <button class="lightbox-nav lightbox-next" @click="lightboxNext">›</button>
      <span class="lightbox-count">{{ lightbox.index + 1 }} / {{ lightbox.images.length }}</span>
      <button class="lightbox-close" @click="closeLightbox">×</button>
    </div>
  </div>
</template>

<style scoped>
.detail-container { padding: 20px; max-width: 900px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.back-btn { background: #252525; border: 1px solid #333; color: #ccc; border-radius: 8px; padding: 8px 16px; cursor: pointer; font-size: 14px; }
.back-btn:hover { color: #fff; }
.detail-topbar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.watchlater-detail-btn { display: inline-flex; align-items: center; gap: 6px; background: #2a2a2a; border: 1px solid #333; color: #bbb; border-radius: 8px; padding: 8px 14px; cursor: pointer; font-size: 14px; }
.watchlater-detail-btn:hover { color: #fff; background: #333; }
.watchlater-detail-btn.active { color: #ffb300; border-color: rgba(255,179,0,0.4); background: rgba(255,179,0,0.12); }
.delete-detail-btn { display: inline-flex; align-items: center; gap: 6px; border: 1px solid #5a2a2a; background: #2a1a1a; color: #ff6b6b; border-radius: 8px; padding: 8px 14px; cursor: pointer; font-size: 14px; }
.delete-detail-btn:hover { background: #3a2020; color: #ff8a8a; }
.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 200px; color: #aaa; }
.spinner { width: 36px; height: 36px; border: 3px solid #333; border-top-color: #2196F3; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { color: #ff6b6b; padding: 12px; background: #2a1a1a; border-radius: 8px; }
.detail-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 14px; padding: 24px; }
.detail-title { font-size: 24px; font-weight: 700; color: #fff; margin: 0 0 8px; }
.detail-meta { color: #888; font-size: 13px; margin-bottom: 16px; }
.detail-content { color: #ddd; font-size: 15px; line-height: 1.7; white-space: pre-wrap; }
.detail-refs { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; margin-top: 16px; }
.ref-block { display: flex; flex-direction: column; gap: 6px; cursor: pointer; }
.ref-note { font-size: 12px; color: #9ecbff; background: #16263a; border-radius: 6px; padding: 4px 8px; align-self: flex-start; }
.no-refs { color: #666; font-size: 13px; }
.inline-ref { display: inline; }
.ref-link { color: #64b5f6; cursor: pointer; text-decoration: underline; text-underline-offset: 2px; }
.ref-link:hover { color: #90caf9; }
.inline-ref :deep(.media-card) { margin: 10px 0; max-width: 320px; }
.inline-gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 8px; margin: 8px 0; max-width: 640px; }
.inline-gallery-img { width: 100%; height: 120px; object-fit: cover; border-radius: 8px; cursor: pointer; background: #000; border: 1px solid #2a2a2a; transition: transform .15s; }
.inline-gallery-img:hover { transform: scale(1.02); border-color: #2196F3; }
.doc-card { display: inline-flex; align-items: center; gap: 10px; padding: 12px 16px; background: #16263a; border: 1px solid #234; border-radius: 10px; color: #cfe6ff; text-decoration: none; cursor: pointer; max-width: 100%; }
.doc-card:hover { border-color: #2196F3; color: #fff; }
.doc-icon { font-size: 22px; }
.doc-name { font-size: 14px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 320px; }
.doc-dl { margin-left: auto; font-size: 12px; color: #64b5f6; background: #0d1b2a; border-radius: 6px; padding: 3px 10px; }
.lightbox { position: fixed; inset: 0; background: rgba(0,0,0,.92); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.lightbox-img { max-width: 92vw; max-height: 92vh; object-fit: contain; border-radius: 6px; }
.lightbox-nav { position: absolute; top: 50%; transform: translateY(-50%); background: rgba(255,255,255,.12); border: none; color: #fff; font-size: 40px; width: 56px; height: 56px; border-radius: 50%; cursor: pointer; }
.lightbox-prev { left: 20px; }
.lightbox-next { right: 20px; }
.lightbox-close { position: absolute; top: 20px; right: 24px; background: none; border: none; color: #fff; font-size: 36px; cursor: pointer; }
.lightbox-count { position: absolute; bottom: 24px; left: 50%; transform: translateX(-50%); color: #ddd; font-size: 14px; background: rgba(0,0,0,.5); padding: 4px 12px; border-radius: 12px; }
</style>
