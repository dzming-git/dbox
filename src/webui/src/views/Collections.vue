<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { collectionSetApi, videoApi, comicApi } from '../api'
import MediaCard from '../components/MediaCard.vue'

const route = useRoute()

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
  if (m.type === 'comic') {
    return { type: 'comic', hash: m.hash, title: m.title, cover: m.cover_url || '', pageCount: m.page_count }
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

const removeItem = async (itemId: number) => {
  if (!activeId.value) return
  try {
    const r = await (collectionSetApi.removeItem(activeId.value, itemId) as any)
    if (r?.success) await loadItems(activeId.value)
  } catch (e) {
    console.error(e)
  }
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
      comicApi.getComics({ search: search.value, limit: 30 }) as any,
    ])
    const vids = (vr?.videos || []).map((v: any) => ({ type: 'video', hash: v.hash, title: v.title, cover: v.thumbnail || '' }))
    const comics = (cr?.comics || []).map((c: any) => ({ type: 'comic', hash: c.hash, title: c.title, cover: c.cover_url || '' }))
    searchResults.value = [...vids, ...comics]
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
          <div class="ci-name">{{ c.name }}</div>
          <div class="ci-meta">{{ c.item_count }} 个资源</div>
          <button class="ci-del" @click="deleteCollection(c.id, $event)" title="删除合集">✕</button>
        </div>
        <div v-if="!collections.length" class="sidebar-empty">还没有合集，点击「新建」创建</div>
      </div>
    </div>

    <div class="content">
      <div class="content-header" v-if="activeId">
        <h3>{{ (collections.find((c) => c.id === activeId) || {}).name || '合集' }}</h3>
        <button class="add-btn" @click="openAdd">+ 添加资源</button>
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
          <input v-model="search" placeholder="搜索视频或漫画..." @input="doSearch" @keyup.enter="doSearch" />
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
              <span class="rc-type">{{ res.type === 'video' ? '视频' : '漫画' }}</span>
            </div>
            <div class="rc-title">{{ res.title }}</div>
          </div>
        </div>
        <div class="modal-empty" v-else-if="searching">搜索中...</div>
        <div class="modal-empty" v-else>输入关键词搜索视频/漫画，点击结果即可加入</div>
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
  background: #141414;
  color: #eee;
}
.sidebar {
  width: 240px;
  flex-shrink: 0;
  border-right: 1px solid #2a2a2a;
  display: flex;
  flex-direction: column;
  background: #181818;
}
.sidebar-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid #2a2a2a;
}
.sidebar-header h2 { font-size: 18px; margin: 0; }
.create-btn {
  background: #2196F3;
  border: none;
  color: #fff;
  border-radius: 6px;
  padding: 6px 10px;
  font-size: 13px;
  cursor: pointer;
}
.create-btn:hover { background: #1976D2; }
.collection-list { flex: 1; overflow-y: auto; padding: 8px; }
.collection-item {
  position: relative;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 4px;
}
.collection-item:hover { background: #242424; }
.collection-item.active { background: #1e3a5f; }
.ci-name { font-size: 14px; font-weight: 500; }
.ci-meta { font-size: 12px; color: #888; margin-top: 2px; }
.ci-del {
  position: absolute;
  top: 8px;
  right: 8px;
  background: transparent;
  border: none;
  color: #888;
  cursor: pointer;
  font-size: 12px;
}
.ci-del:hover { color: #f44336; }
.sidebar-empty { padding: 16px; color: #777; font-size: 13px; line-height: 1.6; }

.content { flex: 1; display: flex; flex-direction: column; overflow: hidden; }
.content-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #2a2a2a;
}
.content-header h3 { margin: 0; font-size: 16px; }
.add-btn {
  background: #2196F3;
  border: none;
  color: #fff;
  border-radius: 6px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
}
.add-btn:hover { background: #1976D2; }
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
  color: #fff;
  cursor: pointer;
  font-size: 13px;
}
.col-card-actions button:hover:not(:disabled) { background: #2196F3; }
.col-card-actions button:disabled { opacity: 0.3; cursor: not-allowed; }
.col-card-actions .del:hover { background: #f44336; }
.col-card-title {
  font-size: 13px;
  color: #ccc;
  margin-top: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.empty { flex: 1; display: flex; align-items: center; justify-content: center; color: #777; }

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
  background: #1e1e1e;
  border: 1px solid #333;
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
  border-bottom: 1px solid #2a2a2a;
}
.modal-header h3 { margin: 0; font-size: 16px; }
.modal-header .close { background: none; border: none; color: #888; font-size: 18px; cursor: pointer; }
.modal-search { display: flex; gap: 8px; padding: 16px; border-bottom: 1px solid #2a2a2a; }
.modal-search input {
  flex: 1;
  background: #141414;
  border: 1px solid #444;
  color: #fff;
  border-radius: 6px;
  padding: 8px 10px;
}
.modal-search button {
  background: #2196F3;
  border: none;
  color: #fff;
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
  background: #2a2a2a center/cover no-repeat;
  border-radius: 8px;
  display: flex;
  align-items: flex-end;
  padding: 6px;
}
.rc-type { background: rgba(0, 0, 0, 0.6); color: #fff; font-size: 11px; padding: 2px 6px; border-radius: 4px; }
.rc-title { font-size: 12px; color: #ccc; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.result-card:hover .rc-cover { outline: 2px solid #2196F3; }
.modal-empty { padding: 24px; text-align: center; color: #777; }

.toast {
  position: fixed;
  bottom: 40px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.85);
  color: #fff;
  padding: 10px 20px;
  border-radius: 8px;
  z-index: 2000;
  font-size: 14px;
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.3s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }

@media (max-width: 767px) {
  .sidebar { width: 140px; }
  .items-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
}
</style>
