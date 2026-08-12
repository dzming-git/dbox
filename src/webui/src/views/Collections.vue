<script setup lang="ts">
import { ref, onMounted, watch, computed, onActivated, onDeactivated } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { collectionSetApi, videoApi, galleryApi } from '../api'
import { useUserStore } from '../stores/userStore'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import MediaCard from '../components/MediaCard.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const collections = ref<any[]>([])
const activeId = ref<number | null>(null)
const items = ref<any[]>([])
const loading = ref(false)
const toast = ref('')
const toastShow = ref(false)

// 添加资源弹窗
const showAdd = ref(false)
const search = ref('')
const searchResults = ref<any[]>([])
const searching = ref(false)

const toastMsg = (m: string) => {
  toast.value = m
  toastShow.value = true
  window.setTimeout(() => (toastShow.value = false), 2000)
}

const toMediaItem = (it: any): any => {
  const m = it.media || it
  if (m.type === 'gallery') {
    return { type: 'gallery', hash: m.hash, title: m.title, cover: m.cover_url || '', pageCount: m.page_count }
  }
  return { type: 'video', hash: m.hash, title: m.title, cover: m.thumbnail || '', duration: m.duration }
}

const loadCollections = async () => {
  try {
    const r = await (collectionSetApi.getCollections() as any)
    collections.value = r?.success ? (r.collections || []) : []
    const cq = route.query.c ? Number(route.query.c) : null
    if (cq && collections.value.some((c: any) => c.id === cq)) {
      activeId.value = cq
    } else if (activeId.value === null && collections.value.length) {
      activeId.value = collections.value[0].id
    } else if (!collections.value.some((c: any) => c.id === activeId.value)) {
      activeId.value = collections.value[0]?.id || null
    }
    if (activeId.value) await loadItems(activeId.value)
  } catch {
    collections.value = []
  }
}

const loadItems = async (id: number) => {
  loading.value = true
  try {
    const r = await (collectionSetApi.getItems(id) as any)
    items.value = r?.success && Array.isArray(r.items) ? r.items : []
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

const select = async (id: number) => {
  activeId.value = id
  await loadItems(id)
}

const createCollection = async () => {
  const name = window.prompt('请输入合集名称')
  if (!name || !name.trim()) return
  try {
    const r = await (collectionSetApi.createCollection({ name: name.trim() }) as any)
    if (r?.success) {
      await loadCollections()
      if (r.collection) await select(r.collection.id)
    }
  } catch (e) {
    console.error(e)
  }
}

const deleteCollection = async (id: number, e: Event) => {
  e.stopPropagation()
  if (!window.confirm('确定删除该合集吗？（合集内的资源不会被删除）')) return
  try {
    const r = await (collectionSetApi.deleteCollection(id) as any)
    if (r?.success) {
      await loadCollections()
      if (activeId.value === id) activeId.value = collections.value[0]?.id || null
      if (activeId.value) await loadItems(activeId.value)
    }
  } catch (e) {
    console.error(e)
  }
}

// 仅作者（owner_key 与当前登录用户一致）或管理员可编辑/删除
const canManage = (c: any): boolean => {
  if (userStore.isAdmin) return true
  const uid = userStore.user?.id
  if (uid && c.owner_key === `u${uid}`) return true
  return false
}

// 编辑合集（重命名 / 简介 / 公开性）
const editingId = ref<number | null>(null)
const editName = ref('')
const editDesc = ref('')
const editPublic = ref(false)
const savingEdit = ref(false)

const startEdit = (c: any, e: Event) => {
  e.stopPropagation()
  editingId.value = c.id
  editName.value = c.name || ''
  editDesc.value = c.description || ''
  editPublic.value = !!c.is_public
}
const cancelEdit = (e: Event) => {
  e.stopPropagation()
  editingId.value = null
}
const saveEdit = async (id: number, e: Event) => {
  e.stopPropagation()
  if (!editName.value.trim()) {
    toastMsg('名称不能为空')
    return
  }
  savingEdit.value = true
  try {
    const r = await (collectionSetApi.updateCollection(id, {
      name: editName.value.trim(),
      description: editDesc.value,
      is_public: editPublic.value,
    }) as any)
    if (r?.success) {
      editingId.value = null
      await loadCollections()
      toastMsg('已保存')
    } else {
      toastMsg(r?.message || '保存失败')
    }
  } catch (err) {
    console.error(err)
    toastMsg('保存失败')
  } finally {
    savingEdit.value = false
  }
}

const removeItem = async (itemId: number) => {
  if (!activeId.value) return
  try {
    const r = await (collectionSetApi.removeItem(activeId.value, itemId) as any)
    if (r?.success) await loadItems(activeId.value)
  } catch (e) {
    console.error(e)
  }
}

// 播放全部：从第一个视频（无视频则第一个资源）开始，带合集上下文跳转
const playAll = () => {
  if (!activeCollection.value || !items.value.length) return
  const firstVideo = items.value.find((i: any) => i.media?.type === 'video')
  const target = firstVideo || items.value[0]
  const t = target.media?.type
  const h = target.media?.hash
  if (t === 'video') router.push(`/video/${h}?collection=${activeId.value}`)
  else router.push(`/gallery/${h}?collection=${activeId.value}`)
}

const move = async (index: number, dir: -1 | 1) => {
  if (!activeId.value) return
  const target = index + dir
  if (target < 0 || target >= items.value.length) return
  const arr = [...items.value]
  const [a] = arr.splice(index, 1)
  arr.splice(target, 0, a)
  items.value = arr
  const ordered = arr.map((i) => i.id)
  try {
    await (collectionSetApi.reorderItems(activeId.value, ordered) as any)
  } catch (e) {
    console.error(e)
    await loadItems(activeId.value)
  }
}

const openAdd = () => {
  showAdd.value = true
  search.value = ''
  searchResults.value = []
}
const closeAdd = () => {
  showAdd.value = false
}

const doSearch = async () => {
  if (!search.value.trim()) {
    searchResults.value = []
    return
  }
  searching.value = true
  try {
    const [vr, cr] = await Promise.all([
      videoApi.getVideos({ search: search.value, limit: 30 }) as any,
      galleryApi.getGallerys({ search: search.value, limit: 30 }) as any,
    ])
    const vids = (vr?.videos || []).map((v: any) => ({ type: 'video', hash: v.hash, title: v.title, cover: v.thumbnail || '' }))
    const galleries = (cr?.galleries || []).map((c: any) => ({ type: 'gallery', hash: c.hash, title: c.title, cover: c.cover_url || '' }))
    searchResults.value = [...vids, ...galleries]
  } catch {
    searchResults.value = []
  } finally {
    searching.value = false
  }
}

const addResource = async (res: any) => {
  if (!activeId.value) return
  try {
    await (collectionSetApi.addItem(activeId.value, { item_type: res.type, item_hash: res.hash }) as any)
    toastMsg('已添加到合集')
    await loadItems(activeId.value)
  } catch (e) {
    console.error(e)
  }
}

onMounted(loadCollections)
watch(
  () => route.query.c,
  () => loadCollections(),
)

// 顶部下拉刷新：重新拉取合集列表
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(loadCollections)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())
</script>

<template>
  <div class="collections">
    <div class="sidebar">
      <div class="sidebar-header">
        <h2>合集</h2>
        <button class="create-btn" @click="createCollection">+ 新建</button>
      </div>
      <div class="collection-list">
        <div
          v-for="c in collections"
          :key="c.id"
          class="collection-item"
          :class="{ active: c.id === activeId }"
          @click="select(c.id)"
        >
          <div class="ci-cover" :style="c.cover_url ? { backgroundImage: `url(${c.cover_url})` } : {}"></div>
          <div class="ci-body">
            <div class="ci-name">{{ c.name }}</div>
            <div class="ci-meta">{{ c.item_count }} 个资源</div>
          </div>
          <!-- 编辑态：内联表单 -->
          <div class="ci-edit" v-if="editingId === c.id" @click.stop>
            <input class="ci-edit-name" v-model="editName" placeholder="合集名称" />
            <textarea class="ci-edit-desc" v-model="editDesc" placeholder="简介（可选）" rows="2"></textarea>
            <label class="ci-edit-public">
              <input type="checkbox" v-model="editPublic" /> 公开合集
            </label>
            <div class="ci-edit-actions">
              <button class="ci-save" :disabled="savingEdit" @click="saveEdit(c.id, $event)">{{ savingEdit ? '保存中' : '保存' }}</button>
              <button class="ci-cancel" @click="cancelEdit($event)">取消</button>
            </div>
          </div>
          <!-- 常态：作者/管理员显示编辑与删除 -->
          <template v-else>
            <button v-if="canManage(c)" class="ci-edit-btn" @click="startEdit(c, $event)" title="编辑合集">✎</button>
            <button class="ci-del" @click="deleteCollection(c.id, $event)" title="删除合集">✕</button>
          </template>
        </div>
        <div v-if="!collections.length" class="sidebar-empty">还没有合集，点击「新建」创建</div>
      </div>
    </div>

    <div class="content">
      <div class="content-header" v-if="activeId">
        <div class="ch-cover" :style="activeCollection?.cover_url ? { backgroundImage: `url(${activeCollection.cover_url})` } : {}"></div>
        <div class="ch-info">
          <h3>{{ (collections.find((c) => c.id === activeId) || {}).name || '合集' }}</h3>
          <span class="ch-meta">{{ items.length }} 个资源 · 点击「播放全部」从第一个视频连播</span>
        </div>
        <button class="add-btn" @click="openAdd">+ 添加资源</button>
        <button class="playall-btn" @click="playAll" :disabled="!items.length">▶ 播放全部</button>
      </div>
      <div class="content-header" v-else>
        <h3>合集</h3>
      </div>

      <div class="items-grid" v-if="items.length">
        <div class="col-card" v-for="(it, idx) in items" :key="it.id">
          <div class="col-card-actions">
            <button @click="move(idx, -1)" :disabled="idx === 0" title="上移">↑</button>
            <button @click="move(idx, 1)" :disabled="idx === items.length - 1" title="下移">↓</button>
            <button class="del" @click="removeItem(it.id)" title="移出合集">✕</button>
          </div>
          <MediaCard :item="toMediaItem(it)" />
          <div class="col-card-title">{{ it.media?.title }}</div>
        </div>
      </div>
      <div class="empty" v-else-if="!loading">
        <p v-if="activeId">该合集还没有资源，点击右上角「添加资源」</p>
        <p v-else>请选择左侧合集，或新建一个合集</p>
      </div>
    </div>

    <!-- 添加资源弹窗 -->
    <div class="modal-overlay" v-if="showAdd" @click.self="closeAdd">
      <div class="modal">
        <div class="modal-header">
          <h3>添加资源到合集</h3>
          <button class="close" @click="closeAdd">✕</button>
        </div>
        <div class="modal-search">
          <input v-model="search" placeholder="搜索视频或图集..." @input="doSearch" @keyup.enter="doSearch" />
          <button @click="doSearch">搜索</button>
        </div>
        <div class="modal-results" v-if="searchResults.length">
          <div
            class="result-card"
            v-for="(res, i) in searchResults"
            :key="i"
            @click="addResource(res)"
          >
            <div class="rc-cover" :style="res.cover ? { backgroundImage: `url(${res.cover})` } : {}">
              <span class="rc-type">{{ res.type === 'video' ? '视频' : '图集' }}</span>
            </div>
            <div class="rc-title">{{ res.title }}</div>
          </div>
        </div>
        <div class="modal-empty" v-else-if="searching">搜索中...</div>
        <div class="modal-empty" v-else>输入关键词搜索视频/图集，点击结果即可加入</div>
      </div>
    </div>

    <transition name="fade">
      <div class="toast" v-if="toastShow">{{ toast }}</div>
    </transition>
  </div>
</template>

<style scoped>
.collections {
  display: flex;
  height: 100%;
  background: var(--bg-surface);
  color: var(--text-primary);
}
.sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid var(--border-default);
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border-default);
}
.sidebar-header h2 { font-size: 18px; margin: 0; }
.create-btn {
  background: var(--accent);
  border: none;
  color: var(--text-on-accent);
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  cursor: pointer;
}
.create-btn:hover { background: var(--accent-active); }
.collection-list { flex: 1; overflow-y: auto; padding: 8px; }
.collection-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 28px 8px 10px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
}
.collection-item:hover { background: var(--bg-surface-hover); }
.collection-item.active { background: var(--info-soft); }
.ci-cover {
  width: 44px;
  height: 44px;
  border-radius: 6px;
  background: var(--bg-surface-hover) center/cover no-repeat;
  flex: 0 0 auto;
}
.ci-body { flex: 1; min-width: 0; }
.ci-name { font-size: 14px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ci-meta { font-size: 12px; color: var(--text-secondary); margin-top: 2px; }
.ci-del {
  position: absolute;
  top: 8px;
  right: 8px;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 12px;
}
.ci-del:hover { color: #f44336; }
.ci-edit-btn {
  position: absolute;
  top: 8px;
  right: 28px;
  background: transparent;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 13px;
  line-height: 1;
}
.ci-edit-btn:hover { color: var(--accent); }
.ci-edit {
  position: absolute;
  top: 4px;
  right: 4px;
  left: 4px;
  z-index: 5;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.5);
}
.ci-edit-name, .ci-edit-desc {
  width: 100%;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  color: var(--text-primary);
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 12px;
  font-family: inherit;
  resize: vertical;
}
.ci-edit-public {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--text-secondary);
}
.ci-edit-actions { display: flex; gap: 8px; }
.ci-edit-actions button {
  flex: 1;
  border: none;
  border-radius: 6px;
  padding: 6px 0;
  font-size: 12px;
  cursor: pointer;
}
.ci-save { background: var(--accent); color: var(--text-on-accent); }
.ci-save:hover { background: var(--accent-active); }
.ci-save:disabled { background: var(--border-strong); cursor: not-allowed; }
.ci-cancel { background: var(--bg-surface-hover); color: var(--text-secondary); }
.ci-cancel:hover { background: var(--border-strong); }
.sidebar-empty { padding: 16px; color: var(--text-tertiary); font-size: 13px; line-height: 1.6; }

.content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.content-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-default);
}
.ch-cover {
  width: 64px;
  height: 64px;
  border-radius: 8px;
  background: var(--bg-surface-hover) center/cover no-repeat;
  flex: 0 0 auto;
}
.ch-info { flex: 1; min-width: 0; }
.ch-info h3 { margin: 0; font-size: 16px; }
.ch-meta { font-size: 12px; color: var(--text-secondary); display: block; margin-top: 4px; }
.add-btn {
  background: var(--accent);
  border: none;
  color: var(--text-on-accent);
  border-radius: 6px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
}
.add-btn:hover { background: var(--accent-active); }
.playall-btn {
  background: #4caf50;
  border: none;
  color: var(--text-on-accent);
  border-radius: 6px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
}
.playall-btn:hover { background: #43a047; }
.playall-btn:disabled { background: var(--border-strong); cursor: not-allowed; }
.items-grid {
  flex: 1;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
  padding: 20px;
}
.col-card { position: relative; }
.col-card-actions {
  position: absolute;
  top: 6px;
  right: 6px;
  display: flex;
  gap: 4px;
  z-index: 2;
}
.col-card-actions button {
  width: 26px;
  height: 26px;
  border-radius: 6px;
  border: none;
  background: rgba(0, 0, 0, 0.6);
  color: var(--text-on-accent);
  cursor: pointer;
  font-size: 13px;
}
.col-card-actions button:hover:not(:disabled) { background: var(--accent); }
.col-card-actions button:disabled { opacity: 0.3; cursor: not-allowed; }
.col-card-actions .del:hover { background: #f44336; }
.col-card-title {
  font-size: 13px;
  color: var(--text-secondary);
  margin-top: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text-tertiary); }

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}
.modal {
  width: 560px;
  max-width: 92vw;
  max-height: 80vh;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border-default);
}
.modal-header h3 { margin: 0; font-size: 16px; }
.modal-header .close { background: none; border: none; color: var(--text-secondary); font-size: 18px; cursor: pointer; }
.modal-search { display: flex; gap: 8px; padding: 16px; border-bottom: 1px solid var(--border-default); }
.modal-search input {
  flex: 1;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  color: var(--text-primary);
  border-radius: 6px;
  padding: 8px 10px;
}
.modal-search button {
  background: var(--accent);
  border: none;
  color: var(--text-on-accent);
  border-radius: 6px;
  padding: 8px 16px;
  cursor: pointer;
}
.modal-results {
  flex: 1;
  overflow-y: auto;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 12px;
  padding: 16px;
}
.result-card { cursor: pointer; }
.rc-cover {
  width: 100%;
  aspect-ratio: 3 / 4;
  background: var(--bg-surface-hover) center/cover no-repeat;
  border-radius: 8px;
  display: flex;
  align-items: flex-end;
  padding: 6px;
}
.rc-type { background: rgba(0, 0, 0, 0.6); color: var(--text-on-accent); font-size: 11px; padding: 2px 6px; border-radius: 4px; }
.rc-title { font-size: 12px; color: var(--text-secondary); margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-card:hover .rc-cover { outline: 2px solid #2196F3; }
.modal-empty { padding: 24px; text-align: center; color: var(--text-tertiary); }

.toast {
  position: fixed;
  bottom: 40px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.85);
  color: var(--text-on-accent);
  padding: 10px 20px;
  border-radius: 8px;
  z-index: 2000;
  font-size: 14px;
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 767px) {
  .collections { flex-direction: column; height: auto; min-height: 100%; }
  .sidebar {
    width: 100%;
    max-height: 116px;
    border-right: none;
    border-bottom: 1px solid var(--border-default);
  }
  .sidebar-header { padding: 10px 12px; }
  .collection-list {
    display: flex;
    flex-direction: row;
    overflow-x: auto;
    gap: 8px;
    padding: 8px 12px;
  }
  .collection-item {
    flex: 0 0 auto;
    width: 150px;
    margin-bottom: 0;
    padding: 6px 10px 6px 8px;
  }
  .ci-del { top: 4px; right: 4px; }
  .ci-edit-btn { top: 4px; right: 24px; }
  .ci-edit {
    position: fixed;
    left: 50%;
    right: auto;
    top: 50%;
    transform: translate(-50%, -50%);
    width: 320px;
    max-width: 90vw;
  }
  .content { overflow: visible; }
  .content-header { flex-wrap: wrap; gap: 10px; padding: 12px; }
  .ch-cover { width: 48px; height: 48px; }
  .ch-info { min-width: 130px; }
  .add-btn, .playall-btn { flex: 1 1 auto; }
  .items-grid { grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); padding: 12px; gap: 10px; }
}
</style>
