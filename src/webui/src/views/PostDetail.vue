<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { postApi } from '../api'
import MediaCard from '../components/MediaCard.vue'

const route = useRoute()
const router = useRouter()

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
    return { type: 'gallery', hash: String(refItem.text.resource_index_id), title: refItem.text.presentation?.title || '文本', cover: refItem.text.presentation?.thumbnail || '', pageCount: 0 }
  }
  if (refItem.presentation) {
    const p = refItem.presentation
    const isVideo = refItem.kind === 'video_file'
    return { type: isVideo ? 'video' : 'gallery', hash: String(refItem.resource_index_id), title: p.title || '未命名资源', cover: p.thumbnail || '', duration: isVideo ? (p.duration || 0) : 0, pageCount: isVideo ? 0 : (p.page_count || 0) }
  }
  return null
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
</script>

<template>
  <div class="detail-container">
    <button class="back-btn" @click="router.back()">← 返回</button>
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
            <MediaCard v-if="seg.ref && seg.mode === 'embed'" :item="toMediaItem(seg.ref)" @click="openRefLink(seg.ref)" />
          </span>
        </template>
      </div>

      <div v-if="orphanRefs(post).length" class="detail-refs">
        <div v-for="(refItem, i) in orphanRefs(post)" :key="refItem.ref_id || i" class="ref-block" @click="openRefLink(refItem)">
          <div v-if="refItem.note" class="ref-note">{{ refItem.note }}</div>
          <MediaCard :item="toMediaItem(refItem)" />
        </div>
      </div>
      <p v-if="!post.content && (!post.refs || !post.refs.length)" class="no-refs">（暂无内容）</p>
    </div>
  </div>
</template>

<style scoped>
.detail-container { padding: 20px; max-width: 900px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.back-btn { background: #252525; border: 1px solid #333; color: #ccc; border-radius: 8px; padding: 8px 16px; cursor: pointer; font-size: 14px; margin-bottom: 16px; }
.back-btn:hover { color: #fff; }
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
</style>
