<script setup lang="ts">
import { ref, onMounted, nextTick, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import { postApi, resourceApi } from '../api'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import type { Post, PostRef, ResourceIndex } from '../types'
import MediaCard from '../components/MediaCard.vue'
import WatchLaterButton from '../components/WatchLaterButton.vue'

const userStore = useUserStore()
const router = useRouter()

const posts = ref<Post[]>([])
const loading = ref(false)
const error = ref('')

const KIND_LABEL: Record<string, string> = {
  video_file: '视频',
  gallery_folder: '图集',
  text: '文本',
}

// 把帖子引用解析为 MediaCard 需要的 MediaItem（含「只属于帖子」资源的兜底呈现）
const toMediaItem = (refItem: PostRef) => {
  // 优先使用后端给出的引用级封面（兼容“帖子专属、无 Gallery/Video 实体”的情况）
  const cover = (refItem as any).cover_url || ''
  if (refItem.video) {
    const v = refItem.video
    return { type: 'video', hash: v.hash, title: v.title, cover: cover || v.thumbnail || '', duration: v.duration || 0, date: v.created_at } as any
  }
  if (refItem.gallery) {
    const c = refItem.gallery
    return { type: 'gallery', hash: c.hash, title: c.title, cover: cover || (c as any).cover_url || '', pageCount: c.page_count || 0, date: c.created_at } as any
  }
  if (refItem.text) {
    return { type: 'gallery', hash: String(refItem.text.resource_index_id), title: refItem.text.presentation?.title || '文本', cover: cover || refItem.text.presentation?.thumbnail || '', pageCount: 0 } as any
  }
  if (refItem.presentation) {
    const p = refItem.presentation
    const isVideo = refItem.kind === 'video_file'
    return {
      type: isVideo ? 'video' : 'gallery',
      hash: String(refItem.resource_index_id),
      title: p.title || '未命名资源',
      cover: cover || p.thumbnail || '',
      duration: isVideo ? (p.duration || 0) : 0,
      pageCount: isVideo ? 0 : (p.page_count || 0),
    } as any
  }
  return null
}

const fetchPosts = async () => {
  loading.value = true
  error.value = ''
  try {
    const res: any = await postApi.list()
    posts.value = res.posts || []
  } catch (e: any) {
    error.value = e?.message || '加载帖子失败'
  } finally {
    loading.value = false
  }
}

onMounted(fetchPosts)

// 顶部下拉刷新：仅作为独立路由（/posts）时注册，嵌入首页时不接管手势
const route = useRoute()
const ptr = usePullToRefresh()
function registerPtr() {
  if (route.name !== 'Posts') return
  ptr.setHandler(fetchPosts)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())
// 供首页 mixed 标签调用
defineExpose({ reload: fetchPosts })

// ============ 新建 / 编辑 ============
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const formTitle = ref('')
const formContent = ref('')          // 正文：纯文本 + 内联资源标记 [文字](res:ID:mode)
const saving = ref(false)
const contentInput = ref<any>(null)  // 正文文本框，用于插入标记时光标定位

// 插入资源弹窗
const resourcePickerVisible = ref(false)
const selectedCandidate = ref<ResourceIndex | null>(null)
const pickerDisplayMode = ref<'embed' | 'link'>('embed')  // 超链接+内嵌预览 / 仅超链接

// 候选资源池（弹窗内选择）
const candidateTab = ref<'video_file' | 'gallery_folder' | 'text'>('video_file')
const candidates = ref<ResourceIndex[]>([])
const candidateSearch = ref('')
const candidatesLoaded = ref(false)

const loadCandidates = async () => {
  try {
    const res: any = await resourceApi.pool({
      kind: candidateTab.value,
      search: candidateSearch.value || undefined,
    })
    candidates.value = res.items || []
  } catch {
    candidates.value = []
  }
  candidatesLoaded.value = true
}

// 内联资源标记解析（与后端 parse_post_content_tokens 对应）
const POST_TOKEN_RE = /\[([^\]]*)\]\(res:(\d+):(link|embed)\)/g

function parseContentTokens(content: string) {
  const out: { resource_index_id: number; mode: string; label: string }[] = []
  if (!content) return out
  POST_TOKEN_RE.lastIndex = 0
  let m: RegExpExecArray | null
  while ((m = POST_TOKEN_RE.exec(content))) {
    out.push({ label: m[1], resource_index_id: parseInt(m[2], 10), mode: m[3] })
  }
  return out
}

function tokenRefIds(content: string) {
  return new Set(parseContentTokens(content).map(t => t.resource_index_id))
}

// 把正文拆成文本段 / 引用段，供视图渲染
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

// 正文未引用的引用（兼容旧帖：引用以列表形式存在，不在正文中）
function orphanRefs(post: any) {
  const ids = tokenRefIds(post.content || '')
  return (post.refs || []).filter((r: any) => !ids.has(r.resource_index_id))
}

function labelForRef(r: any) {
  return r.presentation?.title || r.video?.title || r.gallery?.title || r.text?.title || r.location || ('资源 ' + r.resource_index_id)
}

function openRefLink(r: any) {
  if (!r) return
  if (r.video) { router.push(`/video/${r.video.hash}`); return }
  if (r.gallery) { router.push(`/gallery/${r.gallery.hash}`); return }
  // 文本 / 仅属于帖子的资源没有独立播放页，链接仅作展示
}

const openCreate = async () => {
  editingId.value = null
  formTitle.value = ''
  formContent.value = ''
  candidateTab.value = 'video_file'
  candidates.value = []
  candidateSearch.value = ''
  candidatesLoaded.value = false
  dialogVisible.value = true
  await loadCandidates()
}

const openPost = (d: Post) => {
  const idx = posts.value.findIndex((p) => p.id === d.id)
  const prevId = idx > 0 ? posts.value[idx - 1].id : ''
  const nextId = idx >= 0 && idx < posts.value.length - 1 ? posts.value[idx + 1].id : ''
  const q: Record<string, string> = {}
  if (prevId) q.prev = String(prevId)
  if (nextId) q.next = String(nextId)
  router.push({ path: `/post/${d.id}`, query: q })
}

const openResourcePicker = () => {
  resourcePickerVisible.value = true
  selectedCandidate.value = null
}

const insertResource = () => {
  if (!selectedCandidate.value) return
  const c = selectedCandidate.value
  const label = (c.presentation && c.presentation.title) || c.location || ('资源 ' + c.id)
  const token = `[${label}](res:${c.id}:${pickerDisplayMode.value})`
  const base = contentInput.value
  const el: HTMLTextAreaElement | undefined =
    (base && base.textarea) ? base.textarea : base
  const cur = formContent.value
  if (el) {
    const start = el.selectionStart ?? cur.length
    const end = el.selectionEnd ?? cur.length
    formContent.value = cur.slice(0, start) + token + cur.slice(end)
    nextTick(() => {
      const pos = start + token.length
      el.focus()
      el.setSelectionRange(pos, pos)
    })
  } else {
    formContent.value = cur + token
  }
  resourcePickerVisible.value = false
  selectedCandidate.value = null
}

const save = async () => {
  if (saving.value) return
  saving.value = true
  try {
    const payload = {
      title: formTitle.value,
      content: formContent.value,   // 引用通过正文内联标记表达，后端解析
    }
    if (editingId.value) {
      await postApi.update(editingId.value, payload)
    } else {
      await postApi.create(payload)
    }
    dialogVisible.value = false
    await fetchPosts()
  } catch (e: any) {
    error.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const onSearchCandidate = async () => {
  candidatesLoaded.value = false
  await loadCandidates()
}

const formatDate = (s?: string) => {
  if (!s) return ''
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN')
}
</script>

<template>
  <div class="posts-container">
    <div class="posts-header">
      <h2 class="section-title">帖子</h2>
      <button class="create-btn" @click="openCreate">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 5v14M5 12h14" />
        </svg>
        新建帖子
      </button>
    </div>

    <p class="hint">帖子通过「资源索引表」自由引用视频 / 图集 / 文本。一个资源可同时出现在多个帖子，也可「只属于帖子、不进视频/图集列表」（如下载脚本把图文+视频一体入库到帖子模式）。</p>

    <div v-if="loading" class="loading-container"><div class="spinner"></div><p>加载中...</p></div>
    <div v-else-if="error" class="error-box">{{ error }}</div>
    <div v-else-if="posts.length === 0" class="empty-state">
      <p>还没有帖子，点击「新建帖子」开始创作。</p>
    </div>

    <div v-else class="posts-list">
      <div v-for="d in posts" :key="d.id" class="post-card" @click="openPost(d)">
        <div class="post-head">
          <div class="post-head-main">
            <h3 v-if="d.title" class="post-title">{{ d.title }}</h3>
            <span class="post-date">{{ formatDate(d.created_at) }}</span>
          </div>
          <div class="post-ops" @click.stop>
            <WatchLaterButton variant="compact" type="post" :id="String(d.id)" :title="d.title || '帖子'" />
          </div>
        </div>

        <div v-if="d.content" class="post-content">
          <template v-for="(seg, i) in renderSegments(d.content, d.refs)" :key="i">
            <template v-if="seg.type === 'text'">{{ seg.text }}</template>
            <span v-else class="inline-ref">
              <a class="ref-link" @click="openRefLink(seg.ref)">{{ seg.label }}</a>
              <MediaCard v-if="seg.ref && seg.mode === 'embed'" :item="toMediaItem(seg.ref)" />
            </span>
          </template>
        </div>

        <div v-if="orphanRefs(d).length" class="post-refs">
          <div v-for="(refItem, i) in orphanRefs(d)" :key="refItem.ref_id || i" class="ref-block">
            <div v-if="refItem.note" class="ref-note">{{ refItem.note }}</div>
            <MediaCard :item="toMediaItem(refItem)" />
          </div>
        </div>
        <p v-if="!d.content && (!d.refs || !d.refs.length)" class="no-refs">（暂无内容）</p>
        <div class="post-card-foot">
          <span class="open-hint">查看详情 ›</span>
        </div>
      </div>
    </div>

    <!-- 新建 / 编辑弹窗 -->
    <div v-if="dialogVisible" class="modal-mask" @click.self="dialogVisible = false">
      <div class="modal">
        <h3 class="modal-title">{{ editingId ? '编辑帖子' : '新建帖子' }}</h3>

        <label class="field-label">标题</label>
        <input class="text-input" v-model="formTitle" placeholder="给这条帖子起个标题" />

        <label class="field-label">正文</label>
        <div class="content-toolbar">
          <button type="button" class="insert-res-btn" @click="openResourcePicker">插入资源</button>
          <span class="content-tip">在正文中随时「插入资源」：以超链接方式嵌入，可选择仅超链接或超链接+内嵌预览。</span>
        </div>
        <textarea ref="contentInput" class="text-area" v-model="formContent" rows="6"
          placeholder="写点什么... 例如：今天看了 [一个很棒的片子](res:12:embed)，强烈推荐！"></textarea>

        <div class="modal-ops">
          <button class="cancel-btn" @click="dialogVisible = false">取消</button>
          <button class="save-btn" :disabled="saving" @click="save">{{ saving ? '保存中...' : '保存' }}</button>
        </div>
      </div>
    </div>

    <!-- 插入资源弹窗 -->
    <div v-if="resourcePickerVisible" class="modal-mask" @click.self="resourcePickerVisible = false">
      <div class="modal picker-modal">
        <h3 class="modal-title">插入资源</h3>
        <p class="content-tip">选择一个资源插入到正文光标处，作为超链接；可指定展示方式。</p>

        <div class="picker">
          <div class="picker-tabs">
            <button :class="{ active: candidateTab === 'video_file' }" @click="candidateTab = 'video_file'; candidatesLoaded = false; loadCandidates()">视频</button>
            <button :class="{ active: candidateTab === 'gallery_folder' }" @click="candidateTab = 'gallery_folder'; candidatesLoaded = false; loadCandidates()">图集</button>
            <button :class="{ active: candidateTab === 'text' }" @click="candidateTab = 'text'; candidatesLoaded = false; loadCandidates()">文本</button>
            <input class="picker-search" v-model="candidateSearch" @keyup.enter="onSearchCandidate" placeholder="搜索" />
          </div>
          <div class="picker-grid">
            <div
              v-for="item in candidates"
              :key="item.id"
              class="picker-item"
              :class="{ selected: selectedCandidate && selectedCandidate.id === item.id }"
              @click="selectedCandidate = item"
            >
              <img :src="item.presentation?.thumbnail || ''" class="picker-thumb" />
              <span class="picker-name">{{ item.presentation?.title || item.location }}</span>
            </div>
            <p v-if="candidates.length === 0" class="ref-empty">该模式暂无资源</p>
          </div>
        </div>

        <div class="display-mode">
          <span class="field-label" style="margin:0">展示方式</span>
          <label class="mode-opt"><input type="radio" value="embed" v-model="pickerDisplayMode" /> 超链接 + 内嵌预览</label>
          <label class="mode-opt"><input type="radio" value="link" v-model="pickerDisplayMode" /> 仅超链接</label>
        </div>

        <div class="modal-ops">
          <button class="cancel-btn" @click="resourcePickerVisible = false">取消</button>
          <button class="save-btn" :disabled="!selectedCandidate" @click="insertResource">插入</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.posts-container { padding: 20px; max-width: 1400px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.posts-header { display: flex; align-items: center; justify-content: space-between; }
.section-title { font-size: 20px; font-weight: 600; color: var(--text-primary); margin: 0; }
.create-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border: none; border-radius: 8px;
  background: var(--accent); color: var(--text-on-accent); font-size: 14px; cursor: pointer;
}
.create-btn:hover { background: var(--accent-active); }
.hint { color: var(--text-secondary); font-size: 13px; margin: 8px 0 16px; line-height: 1.5; }

.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 200px; color: var(--text-secondary); }
.spinner { width: 36px; height: 36px; border: 3px solid var(--border-default); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { color: var(--danger); padding: 12px; background: var(--danger-soft); border-radius: 8px; }
.empty-state { color: var(--text-tertiary); text-align: center; padding: 60px 0; }

.posts-list { display: flex; flex-direction: column; gap: 20px; }
.post-card { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 14px; padding: 18px; cursor: pointer; transition: border-color 0.15s, transform 0.15s; }
.post-card:hover { border-color: var(--accent); transform: translateY(-2px); }
.post-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.post-head-main { cursor: pointer; display: flex; align-items: baseline; gap: 10px; flex: 1; min-width: 0; }
.post-card:hover .post-title { color: var(--accent); }
.post-title { font-size: 17px; font-weight: 600; color: var(--text-primary); margin: 0; }
.post-title--empty { color: var(--text-tertiary); font-weight: 500; }
.post-date { font-size: 12px; color: var(--text-tertiary); }
.post-ops { display: flex; gap: 8px; flex-shrink: 0; }
.post-card-foot { display: flex; justify-content: flex-end; margin-top: 12px; }
.open-hint { font-size: 13px; color: var(--accent); opacity: 0; transition: opacity 0.15s; }
.post-card:hover .open-hint { opacity: 1; }
.op-btn { padding: 5px 12px; border: 1px solid var(--border-default); background: var(--bg-surface-hover); color: var(--text-secondary); border-radius: 6px; font-size: 13px; cursor: pointer; }
.op-btn:hover { color: var(--accent); }
.op-btn.danger:hover { color: var(--danger); border-color: var(--danger); }
.post-content { color: var(--text-secondary); font-size: 14px; line-height: 1.6; margin: 12px 0; white-space: pre-wrap; }

.post-refs { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; margin-top: 8px; }
.ref-block { display: flex; flex-direction: column; gap: 6px; }
.ref-note { font-size: 12px; color: var(--text-secondary); background: var(--info-soft); border-radius: 6px; padding: 4px 8px; align-self: flex-start; }
.no-refs { color: var(--text-tertiary); font-size: 13px; }

/* 弹窗 */
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 20px; }
.modal { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 14px; padding: 24px; width: 100%; max-width: 820px; max-height: 90vh; overflow-y: auto; }
.modal-title { color: var(--text-primary); margin: 0 0 16px; font-size: 18px; }
.field-label { display: block; color: var(--text-secondary); font-size: 13px; margin: 14px 0 6px; }
.text-input, .text-area { width: 100%; box-sizing: border-box; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 8px; color: var(--text-primary); padding: 10px 12px; font-size: 14px; font-family: inherit; }
.text-area { resize: vertical; }
.text-input:focus, .text-area:focus { outline: none; border-color: var(--accent); }

.content-toolbar { display: flex; align-items: center; gap: 12px; margin: 6px 0; flex-wrap: wrap; }
.insert-res-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border: 1px solid #2196F3; border-radius: 8px;
  background: rgba(33,150,243,0.12); color: var(--accent); font-size: 13px; cursor: pointer; white-space: nowrap;
}
.insert-res-btn:hover { background: rgba(33,150,243,0.24); color: #90caf9; }
.content-tip { color: var(--text-secondary); font-size: 12px; line-height: 1.5; }

/* 正文内联引用 */
.inline-ref { display: inline; }
.ref-link {
  color: var(--accent); cursor: pointer; text-decoration: underline; text-underline-offset: 2px;
}
.ref-link:hover { color: #90caf9; }
.inline-ref :deep(.media-card) { margin: 10px 0; max-width: 320px; }

.ref-empty { color: var(--text-tertiary); font-size: 13px; }

/* 插入资源弹窗 */
.picker-modal { max-width: 720px; }
.display-mode { display: flex; align-items: center; gap: 18px; margin-top: 16px; flex-wrap: wrap; }
.mode-opt { display: inline-flex; align-items: center; gap: 6px; color: var(--text-secondary); font-size: 13px; cursor: pointer; }
.mode-opt input { accent-color: var(--accent); }

.picker { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 8px; padding: 10px; min-height: 220px; display: flex; flex-direction: column; }
.picker-tabs { display: flex; gap: 6px; margin-bottom: 8px; align-items: center; }
.picker-tabs button { padding: 5px 12px; border: 1px solid var(--border-default); background: var(--bg-surface-hover); color: var(--text-secondary); border-radius: 6px; cursor: pointer; font-size: 13px; }
.picker-tabs button.active { background: var(--accent); color: var(--text-on-accent); border-color: var(--accent); }
.picker-search { margin-left: auto; width: 120px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 6px; color: var(--text-secondary); padding: 5px 8px; font-size: 12px; }
.picker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 8px; overflow-y: auto; flex: 1; }
.picker-item { position: relative; cursor: pointer; border: 2px solid transparent; border-radius: 8px; overflow: hidden; background: #000; }
.picker-item.selected { border-color: var(--accent); }
.picker-thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; background: var(--bg-surface-2); }
.picker-name { display: block; font-size: 11px; color: var(--text-secondary); padding: 2px 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.modal-ops { display: flex; justify-content: flex-end; gap: 12px; margin-top: 20px; }
.cancel-btn { padding: 8px 18px; border: 1px solid var(--border-default); background: var(--bg-surface-hover); color: var(--text-secondary); border-radius: 8px; cursor: pointer; }
.cancel-btn:hover { color: var(--accent); }
.save-btn { padding: 8px 22px; border: none; border-radius: 8px; background: var(--accent); color: var(--text-on-accent); font-size: 14px; cursor: pointer; }
.save-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.save-btn:hover:not(:disabled) { background: var(--accent-active); }
</style>