<script setup lang="ts">
import { ref, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { galleryApi } from '../api'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import GalleryCard from '../components/GalleryCard.vue'

const router = useRouter()
const playlists = ref<any[]>([])
const loading = ref(false)
const showCreate = ref(false)
const newName = ref('')
const newDesc = ref('')
const newPublic = ref(false)
const selected = ref<any>(null)

const load = async () => {
  loading.value = true
  try {
    const res: any = await galleryApi.getPlaylists()
    playlists.value = res.playlists || []
  } catch {
    playlists.value = []
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  showCreate.value = true
  newName.value = ''
  newDesc.value = ''
  newPublic.value = false
}

const create = async () => {
  if (!newName.value.trim()) return
  const res: any = await galleryApi.createPlaylist({
    name: newName.value.trim(),
    description: newDesc.value,
    is_public: newPublic.value,
  })
  if (res.success) {
    showCreate.value = false
    await load()
  }
}

const removeFrom = async (pl: any, hash: string) => {
  await galleryApi.removeFromPlaylist(pl.id, hash)
  await load()
}

const del = async () => {
  if (selected.value) {
    await galleryApi.deletePlaylist(selected.value.id)
    selected.value = null
    await load()
  }
}

const goGallery = (c: any) => router.push({ name: 'Gallery', params: { hash: c.hash } })

onMounted(load)

// 顶部下拉刷新：重新加载图集播放列表
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(load)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())
</script>

<template>
  <div class="playlists-container">
    <div class="header">
      <h1>图集合集</h1>
      <button class="create-btn" @click="openCreate">新建合集</button>
    </div>

    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="playlists.length === 0" class="empty">还没有合集，点击「新建合集」开始。</div>
    <div v-else class="playlist-grid">
      <div
        v-for="pl in playlists"
        :key="pl.id"
        class="playlist-card"
        :class="{ active: selected && selected.id === pl.id }"
        @click="selected = (selected && selected.id === pl.id ? null : pl)"
      >
        <div class="pl-head">
          <h3>{{ pl.name }}</h3>
          <span v-if="pl.is_public" class="badge">公开</span>
        </div>
        <p class="pl-desc">{{ pl.description || '暂无简介' }}</p>
        <div class="pl-meta">{{ pl.gallery_count }} 本 · 播放 {{ pl.play_count }}</div>
      </div>
    </div>

    <div v-if="selected" class="detail">
      <div class="detail-head">
        <h2>{{ selected.name }}</h2>
        <button class="del-btn" @click="del">删除合集</button>
      </div>
      <div v-if="(selected.items || []).length === 0" class="empty">合集内暂无图集</div>
      <div v-else class="detail-grid">
        <div v-for="it in selected.items" :key="it.id" class="detail-item">
          <GalleryCard :gallery="it.gallery" :size="'small'" @click="goGallery" />
          <button class="remove-btn" @click="removeFrom(selected, it.gallery.hash)">移除</button>
        </div>
      </div>
    </div>

    <div v-if="showCreate" class="dialog-overlay" @click.self="showCreate = false">
      <div class="dialog">
        <h3>新建合集</h3>
        <input v-model="newName" class="fld" placeholder="合集名称" />
        <textarea v-model="newDesc" class="fld" placeholder="简介（选填）" rows="3"></textarea>
        <label class="pub"><input type="checkbox" v-model="newPublic" /> 公开合集</label>
        <div class="dialog-actions">
          <button @click="showCreate = false">取消</button>
          <button class="primary" @click="create">创建</button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.playlists-container { padding: 20px; max-width: 1200px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 20px; }
.header h1 { font-size: 24px; font-weight: 600; color: var(--text-primary); margin: 0; }
.create-btn { padding: 10px 18px; background: var(--accent); border: none; border-radius: 8px; color: var(--text-on-accent); font-size: 14px; cursor: pointer; }
.loading, .empty { color: var(--text-secondary); text-align: center; padding: 60px 0; }
.playlist-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px; }
.playlist-card { background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 12px; padding: 16px; cursor: pointer; transition: border-color 0.2s; }
.playlist-card:hover { border-color: var(--accent); }
.playlist-card.active { border-color: var(--accent); background: var(--info-soft); }
.pl-head { display: flex; align-items: center; justify-content: space-between; }
.pl-head h3 { font-size: 16px; color: var(--text-primary); margin: 0; }
.badge { font-size: 11px; padding: 2px 8px; border-radius: 4px; background: #4caf50; color: var(--text-on-accent); }
.pl-desc { color: var(--text-tertiary); font-size: 13px; margin: 8px 0; min-height: 18px; }
.pl-meta { color: var(--text-tertiary); font-size: 12px; }
.detail { margin-top: 28px; border-top: 1px solid var(--border-default); padding-top: 20px; }
.detail-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.detail-head h2 { font-size: 20px; color: var(--text-primary); margin: 0; }
.del-btn { padding: 8px 14px; background: rgba(255,107,107,0.15); border: 1px solid rgba(255,107,107,0.3); border-radius: 6px; color: var(--danger); cursor: pointer; font-size: 13px; }
.detail-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 16px; }
.detail-item { position: relative; }
.remove-btn { position: absolute; top: 6px; right: 6px; z-index: 5; padding: 4px 8px; background: rgba(0,0,0,0.6); border: none; border-radius: 4px; color: var(--text-on-accent); font-size: 12px; cursor: pointer; }
.dialog-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.8); display: flex; align-items: center; justify-content: center; z-index: 1000; }
.dialog { background: var(--bg-surface-hover); border-radius: 16px; padding: 24px; width: 420px; max-width: 90vw; }
.dialog h3 { color: var(--text-primary); margin: 0 0 16px; }
.fld { width: 100%; box-sizing: border-box; padding: 10px 12px; background: var(--bg-surface); border: 1px solid var(--border-strong); border-radius: 8px; color: var(--text-primary); font-size: 14px; margin-bottom: 12px; font-family: inherit; }
.fld:focus { outline: none; border-color: var(--accent); }
.pub { display: flex; align-items: center; gap: 8px; color: var(--text-secondary); font-size: 14px; margin-bottom: 16px; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 12px; }
.dialog-actions button { padding: 10px 18px; border-radius: 6px; border: 1px solid var(--border-strong); background: var(--bg-surface-2); color: var(--text-primary); cursor: pointer; font-size: 14px; }
.dialog-actions .primary { background: var(--accent); border-color: var(--accent); color: var(--text-on-accent); }
</style>
