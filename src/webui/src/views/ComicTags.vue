<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { comicApi } from '../api'

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
    const res: any = await comicApi.getComicTags({ tree: true })
    tags.value = flatten(res.tags || [])
  } catch {
    tags.value = []
  } finally {
    loading.value = false
  }
}

const viewComics = (tag: any) => {
  router.push({ path: '/comics', query: { tag: String(tag.id) } })
}

onMounted(loadTags)
</script>

<template>
  <div class="comic-tags-container">
    <h1 class="page-title">漫画标签</h1>
    <p class="page-desc">按标签浏览漫画（数量基于你有权限查看的视频库）。</p>
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
          <span class="tag-count">{{ t.comic_count }}</span>
          <button
            class="tag-view-btn"
            :disabled="!t.comic_count"
            @click="viewComics(t)"
          >查看漫画</button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.comic-tags-container { padding: 20px; max-width: 900px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.page-title { font-size: 24px; font-weight: 600; color: #fff; margin: 0 0 6px; }
.page-desc { color: #999; font-size: 14px; margin: 0 0 20px; }
.loading, .empty { color: #888; text-align: center; padding: 60px 0; }
.tag-tree { list-style: none; margin: 0; padding: 0; background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px; overflow: hidden; }
.tag-node { border-bottom: 1px solid #222; }
.tag-node:last-child { border-bottom: none; }
.tag-row { display: flex; align-items: center; gap: 12px; padding: 12px 16px; }
.tag-name { flex: 1; color: #fff; font-size: 15px; }
.tag-count { color: #888; font-size: 13px; min-width: 32px; text-align: right; }
.tag-view-btn { padding: 6px 14px; background: #2196F3; border: none; border-radius: 6px; color: #fff; font-size: 13px; cursor: pointer; }
.tag-view-btn:disabled { background: #333; color: #777; cursor: not-allowed; }
</style>
