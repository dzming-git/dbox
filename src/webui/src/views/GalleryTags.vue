<script setup lang="ts">
import { ref, onMounted, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { galleryApi } from '../api'
import { usePullToRefresh } from '../composables/usePullToRefresh'

const router = useRouter()
const tags = ref<any[]>([])
const loading = ref(false)

const flatten = (list: any[], depth = 0, out: any[] = []): any[] => {
  for (const t of list) {
    out.push({ ...t, depth })
    if (t.children && t.children.length) flatten(t.children, depth + 1, out)
  }
  return out
}

const loadTags = async () => {
  loading.value = true
  try {
    const res: any = await galleryApi.getGalleryTags({ tree: true })
    tags.value = flatten(res.tags || [])
  } catch {
    tags.value = []
  } finally {
    loading.value = false
  }
}

const viewGallerys = (tag: any) => {
  router.push({ path: '/galleries', query: { tag: String(tag.id) } })
}

onMounted(loadTags)

// 顶部下拉刷新：重新加载图集标签
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(loadTags)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())
</script>

<template>
  <div class="gallery-tags-container">
    <h1 class="page-title">图集标签</h1>
    <p class="page-desc">按标签浏览图集（数量基于你有权限查看的资源库）。</p>
    <div v-if="loading" class="loading">加载中...</div>
    <div v-else-if="tags.length === 0" class="empty">暂无标签</div>
    <ul v-else class="tag-tree">
      <li
        v-for="t in tags"
        :key="t.id"
        class="tag-node"
        :style="{ paddingLeft: t.depth * 22 + 12 + 'px' }"
      >
        <div class="tag-row">
          <span class="tag-name">{{ t.name }}</span>
          <span class="tag-count">{{ t.gallery_count }}</span>
          <button
            class="tag-view-btn"
            :disabled="!t.gallery_count"
            @click="viewGallerys(t)"
          >查看图集</button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.gallery-tags-container { padding: 20px; max-width: 900px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.page-title { font-size: 24px; font-weight: 600; color: var(--text-primary); margin: 0 0 6px; }
.page-desc { color: var(--text-tertiary); font-size: 14px; margin: 0 0 20px; }
.loading, .empty { color: var(--text-secondary); text-align: center; padding: 60px 0; }
.tag-tree { list-style: none; margin: 0; padding: 0; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 12px; overflow: hidden; }
.tag-node { border-bottom: 1px solid var(--bg-surface-2); }
.tag-node:last-child { border-bottom: none; }
.tag-row { display: flex; align-items: center; gap: 12px; padding: 12px 16px; }
.tag-name { flex: 1; color: var(--text-primary); font-size: 15px; }
.tag-count { color: var(--text-secondary); font-size: 13px; min-width: 32px; text-align: right; }
.tag-view-btn { padding: 6px 14px; background: var(--accent); border: none; border-radius: 6px; color: var(--text-on-accent); font-size: 13px; cursor: pointer; }
.tag-view-btn:disabled { background: var(--bg-surface-2); color: var(--text-tertiary); cursor: not-allowed; }
</style>
