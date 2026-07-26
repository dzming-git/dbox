<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import { dynamicApi, videoApi, comicApi } from '../api'
import type { Dynamic, DynamicRef, Video, Comic } from '../types'
import MediaCard from '../components/MediaCard.vue'

const router = useRouter()
const userStore = useUserStore()

const dynamics = ref<Dynamic[]>([])
const loading = ref(false)
const error = ref('')

// 把动态引用解析为 MediaCard 需要的 MediaItem
const toMediaItem = (refItem: DynamicRef) => {
  if (refItem.video) {
    const v = refItem.video as Video
    return {
      type: 'video',
      hash: v.hash,
      title: v.title,
      cover: v.thumbnail || '',
      duration: v.duration || 0,
      date: v.created_at
    } as any
  }
  if (refItem.comic) {
    const c = refItem.comic as Comic
    return {
      type: 'comic',
      hash: c.hash,
      title: c.title,
      cover: (c as any).cover_url || '',
      pageCount: c.page_count || 0,
      date: c.created_at
    } as any
  }
  return null
}

const fetchDynamics = async () => {
  loading.value = true
  error.value = ''
  try {
    const res: any = await dynamicApi.list()
    dynamics.value = res.dynamics || []
  } catch (e: any) {
    error.value = e?.message || '加载动态失败'
  } finally {
    loading.value = false
  }
}

onMounted(fetchDynamics)

// ============ 新建 / 编辑 ============
const dialogVisible = ref(false)
const editingId = ref<number | null>(null)
const formTitle = ref('')
const formContent = ref('')
const editingRefs = ref<Array<{ type: 'video' | 'comic'; id: number; title: string; cover: string; note: string }>>([])
const saving = ref(false)

// 引用选择器的候选池
const candidateTab = ref<'video' | 'comic'>('video')
const videoCandidates = ref<Video[]>([])
const comicCandidates = ref<Comic[]>([])
const candidateSearch = ref('')
const candidatesLoaded = ref(false)

const loadCandidates = async () => {
  if (candidatesLoaded.value) return
  try {
    const [vRes, cRes] = await Promise.allSettled([
      videoApi.getVideos({ limit: 60, search: candidateSearch.value || undefined }) as any,
      comicApi.getComics({ limit: 60, search: candidateSearch.value || undefined }) as any
    ])
    if (vRes.status === 'fulfilled') videoCandidates.value = vRes.value?.videos || []
    if (cRes.status === 'fulfilled') comicCandidates.value = cRes.value?.comics || []
    candidatesLoaded.value = true
  } catch {
    /* ignore */
  }
}

const isSelected = (type: 'video' | 'comic', id: number) =>
  editingRefs.value.some(r => r.type === type && r.id === id)

const toggleCandidate = (type: 'video' | 'comic', item: any) => {
  const idx = editingRefs.value.findIndex(r => r.type === type && r.id === item.id)
  if (idx >= 0) {
    editingRefs.value.splice(idx, 1)
  } else {
    editingRefs.value.push({
      type,
      id: item.id,
      title: item.title,
      cover: type === 'video' ? (item.thumbnail || '') : (item.cover_url || ''),
      note: ''
    })
  }
}

const moveRef = (index: number, dir: -1 | 1) => {
  const target = index + dir
  if (target < 0 || target >= editingRefs.value.length) return
  const arr = editingRefs.value
  ;[arr[index], arr[target]] = [arr[target], arr[index]]
}

const openCreate = async () => {
  editingId.value = null
  formTitle.value = ''
  formContent.value = ''
  editingRefs.value = []
  candidatesLoaded.value = false
  videoCandidates.value = []
  comicCandidates.value = []
  dialogVisible.value = true
  await loadCandidates()
}

const openEdit = async (d: Dynamic) => {
  editingId.value = d.id
  formTitle.value = d.title
  formContent.value = d.content
  editingRefs.value = (d.refs || []).map(r => ({
    type: r.video ? 'video' : 'comic',
    id: (r.video ? r.video.id : r.comic?.id) as number,
    title: (r.video ? r.video.title : r.comic?.title) as string,
    cover: (r.video ? r.video.thumbnail : (r.comic as any)?.cover_url) || '',
    note: r.note || ''
  }))
  candidatesLoaded.value = false
  videoCandidates.value = []
  comicCandidates.value = []
  dialogVisible.value = true
  await loadCandidates()
}

const save = async () => {
  if (saving.value) return
  saving.value = true
  try {
    const payload = {
      title: formTitle.value,
      content: formContent.value,
      refs: editingRefs.value.map(r => ({ type: r.type, id: r.id, note: r.note }))
    }
    if (editingId.value) {
      await dynamicApi.update(editingId.value, payload)
    } else {
      await dynamicApi.create(payload)
    }
    dialogVisible.value = false
    await fetchDynamics()
  } catch (e: any) {
    error.value = e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const removeDynamic = async (d: Dynamic) => {
  if (!confirm(`确定删除动态「${d.title || '未命名'}」？`)) return
  try {
    await dynamicApi.remove(d.id)
    await fetchDynamics()
  } catch (e: any) {
    error.value = e?.message || '删除失败'
  }
}

const canEdit = (d: Dynamic) =>
  userStore.user && (userStore.user.id === d.owner_id || userStore.user.role >= 2)

const onSearchCandidate = async () => {
  candidatesLoaded.value = false
  videoCandidates.value = []
  comicCandidates.value = []
  await loadCandidates()
}

const formatDate = (s?: string) => {
  if (!s) return ''
  const d = new Date(s)
  return isNaN(d.getTime()) ? s : d.toLocaleString('zh-CN')
}
</script>

<template>
  <div class="dynamics-container">
    <div class="dynamics-header">
      <h2 class="section-title">动态</h2>
      <button class="create-btn" @click="openCreate">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 5v14M5 12h14" />
        </svg>
        新建动态
      </button>
    </div>

    <p class="hint">动态通过「资源索引表」自由引用视频 / 图片集（漫画），同一资源可被多个动态共享，移动磁盘资源只需更新索引一行。</p>

    <div v-if="loading" class="loading-container"><div class="spinner"></div><p>加载中...</p></div>
    <div v-else-if="error" class="error-box">{{ error }}</div>
    <div v-else-if="dynamics.length === 0" class="empty-state">
      <p>还没有动态，点击「新建动态」开始创作。</p>
    </div>

    <div v-else class="dynamics-list">
      <div v-for="d in dynamics" :key="d.id" class="dynamic-card">
        <div class="dynamic-head">
          <div>
            <h3 class="dynamic-title">{{ d.title || '未命名动态' }}</h3>
            <span class="dynamic-date">{{ formatDate(d.created_at) }}</span>
          </div>
          <div v-if="canEdit(d)" class="dynamic-ops">
            <button class="op-btn" title="编辑" @click="openEdit(d)">编辑</button>
            <button class="op-btn danger" title="删除" @click="removeDynamic(d)">删除</button>
          </div>
        </div>

        <p v-if="d.content" class="dynamic-content">{{ d.content }}</p>

        <div v-if="d.refs && d.refs.length" class="dynamic-refs">
          <div v-for="(refItem, i) in d.refs" :key="refItem.ref_id || i" class="ref-block">
            <div v-if="refItem.note" class="ref-note">{{ refItem.note }}</div>
            <MediaCard :item="toMediaItem(refItem)" />
          </div>
        </div>
        <p v-else class="no-refs">（暂无引用资源）</p>
      </div>
    </div>

    <!-- 新建 / 编辑弹窗 -->
    <div v-if="dialogVisible" class="modal-mask" @click.self="dialogVisible = false">
      <div class="modal">
        <h3 class="modal-title">{{ editingId ? '编辑动态' : '新建动态' }}</h3>

        <label class="field-label">标题</label>
        <input class="text-input" v-model="formTitle" placeholder="给这条动态起个标题" />

        <label class="field-label">正文</label>
        <textarea class="text-area" v-model="formContent" rows="4" placeholder="写点什么..."></textarea>

        <label class="field-label">引用资源（视频 / 图片集）</label>
        <div class="ref-editor">
          <div class="ref-list">
            <p v-if="editingRefs.length === 0" class="ref-empty">尚未选择任何引用，下面从资源池添加。</p>
            <div v-for="(r, i) in editingRefs" :key="i" class="ref-row">
              <span class="ref-type" :class="r.type">{{ r.type === 'video' ? '视频' : '图片集' }}</span>
              <span class="ref-name">{{ r.title }}</span>
              <input class="ref-note-input" v-model="r.note" placeholder="备注（可选）" />
              <button class="ref-move" @click="moveRef(i, -1)" title="上移">↑</button>
              <button class="ref-move" @click="moveRef(i, 1)" title="下移">↓</button>
              <button class="ref-del" @click="editingRefs.splice(i, 1)" title="移除">✕</button>
            </div>
          </div>

          <div class="picker">
            <div class="picker-tabs">
              <button :class="{ active: candidateTab === 'video' }" @click="candidateTab = 'video'">视频</button>
              <button :class="{ active: candidateTab === 'comic' }" @click="candidateTab = 'comic'">图片集</button>
              <input class="picker-search" v-model="candidateSearch" @keyup.enter="onSearchCandidate" placeholder="搜索" />
            </div>
            <div class="picker-grid">
              <div
                v-for="item in candidateTab === 'video' ? videoCandidates : comicCandidates"
                :key="item.id"
                class="picker-item"
                :class="{ selected: isSelected(candidateTab, item.id) }"
                @click="toggleCandidate(candidateTab, item)"
              >
                <img :src="candidateTab === 'video' ? (item.thumbnail || '') : (item.cover_url || '')" class="picker-thumb" />
                <span class="picker-name">{{ item.title }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="modal-ops">
          <button class="cancel-btn" @click="dialogVisible = false">取消</button>
          <button class="save-btn" :disabled="saving" @click="save">{{ saving ? '保存中...' : '保存' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.dynamics-container { padding: 20px; max-width: 1400px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.dynamics-header { display: flex; align-items: center; justify-content: space-between; }
.section-title { font-size: 20px; font-weight: 600; color: #fff; margin: 0; }
.create-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 8px 16px; border: none; border-radius: 8px;
  background: #2196F3; color: #fff; font-size: 14px; cursor: pointer;
}
.create-btn:hover { background: #1976D2; }
.hint { color: #888; font-size: 13px; margin: 8px 0 16px; line-height: 1.5; }

.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 200px; color: #aaa; }
.spinner { width: 36px; height: 36px; border: 3px solid #333; border-top-color: #2196F3; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { color: #ff6b6b; padding: 12px; background: #2a1a1a; border-radius: 8px; }
.empty-state { color: #666; text-align: center; padding: 60px 0; }

.dynamics-list { display: flex; flex-direction: column; gap: 20px; }
.dynamic-card { background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 14px; padding: 18px; }
.dynamic-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.dynamic-title { font-size: 17px; font-weight: 600; color: #fff; margin: 0; }
.dynamic-date { font-size: 12px; color: #777; }
.dynamic-ops { display: flex; gap: 8px; flex-shrink: 0; }
.op-btn { padding: 5px 12px; border: 1px solid #3a3a3a; background: #252525; color: #ccc; border-radius: 6px; font-size: 13px; cursor: pointer; }
.op-btn:hover { color: #fff; }
.op-btn.danger:hover { color: #ff6b6b; border-color: #ff6b6b; }
.dynamic-content { color: #ddd; font-size: 14px; line-height: 1.6; margin: 12px 0; white-space: pre-wrap; }

.dynamic-refs { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 14px; margin-top: 8px; }
.ref-block { display: flex; flex-direction: column; gap: 6px; }
.ref-note { font-size: 12px; color: #9ecbff; background: #16263a; border-radius: 6px; padding: 4px 8px; align-self: flex-start; }
.no-refs { color: #666; font-size: 13px; }

/* 弹窗 */
.modal-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 20px; }
.modal { background: #1f1f1f; border: 1px solid #333; border-radius: 14px; padding: 24px; width: 100%; max-width: 820px; max-height: 90vh; overflow-y: auto; }
.modal-title { color: #fff; margin: 0 0 16px; font-size: 18px; }
.field-label { display: block; color: #aaa; font-size: 13px; margin: 14px 0 6px; }
.text-input, .text-area { width: 100%; box-sizing: border-box; background: #141414; border: 1px solid #3a3a3a; border-radius: 8px; color: #fff; padding: 10px 12px; font-size: 14px; font-family: inherit; }
.text-area { resize: vertical; }
.text-input:focus, .text-area:focus { outline: none; border-color: #2196F3; }

.ref-editor { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 8px; }
@media (max-width: 700px) { .ref-editor { grid-template-columns: 1fr; } }
.ref-list { background: #141414; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px; min-height: 220px; }
.ref-empty { color: #666; font-size: 13px; }
.ref-row { display: flex; align-items: center; gap: 8px; padding: 6px 0; border-bottom: 1px solid #262626; }
.ref-type { font-size: 11px; padding: 2px 8px; border-radius: 4px; color: #fff; }
.ref-type.video { background: rgba(33,150,243,0.85); }
.ref-type.comic { background: rgba(255,152,0,0.85); }
.ref-name { flex: 1; color: #ddd; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ref-note-input { width: 90px; background: #1a1a1a; border: 1px solid #333; border-radius: 6px; color: #ccc; padding: 4px 6px; font-size: 12px; }
.ref-move, .ref-del { width: 26px; height: 26px; border: 1px solid #333; background: #252525; color: #aaa; border-radius: 6px; cursor: pointer; }
.ref-del:hover { color: #ff6b6b; border-color: #ff6b6b; }

.picker { background: #141414; border: 1px solid #2a2a2a; border-radius: 8px; padding: 10px; min-height: 220px; display: flex; flex-direction: column; }
.picker-tabs { display: flex; gap: 6px; margin-bottom: 8px; align-items: center; }
.picker-tabs button { padding: 5px 12px; border: 1px solid #333; background: #252525; color: #aaa; border-radius: 6px; cursor: pointer; font-size: 13px; }
.picker-tabs button.active { background: #2196F3; color: #fff; border-color: #2196F3; }
.picker-search { margin-left: auto; width: 120px; background: #1a1a1a; border: 1px solid #333; border-radius: 6px; color: #ccc; padding: 5px 8px; font-size: 12px; }
.picker-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(80px, 1fr)); gap: 8px; overflow-y: auto; flex: 1; }
.picker-item { position: relative; cursor: pointer; border: 2px solid transparent; border-radius: 8px; overflow: hidden; background: #000; }
.picker-item.selected { border-color: #2196F3; }
.picker-thumb { width: 100%; aspect-ratio: 16/9; object-fit: cover; display: block; }
.picker-name { display: block; font-size: 11px; color: #ccc; padding: 2px 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.modal-ops { display: flex; justify-content: flex-end; gap: 12px; margin-top: 20px; }
.cancel-btn { padding: 8px 18px; border: 1px solid #3a3a3a; background: #252525; color: #ccc; border-radius: 8px; cursor: pointer; }
.cancel-btn:hover { color: #fff; }
.save-btn { padding: 8px 22px; border: none; border-radius: 8px; background: #2196F3; color: #fff; font-size: 14px; cursor: pointer; }
.save-btn:disabled { opacity: 0.6; cursor: not-allowed; }
.save-btn:hover:not(:disabled) { background: #1976D2; }
</style>
