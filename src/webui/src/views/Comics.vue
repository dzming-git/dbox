<script setup lang="ts">
import { ref, onMounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useComicStore } from '../stores/comicStore'
import { useUserStore } from '../stores/userStore'
import ComicCard from '../components/ComicCard.vue'
import ItemEditDrawer from '../components/ItemEditDrawer.vue'
import type { Comic } from '../types'
import { comicApi } from '../api'

const router = useRouter()
const route = useRoute()
const comicStore = useComicStore()
const userStore = useUserStore()

// 标签筛选（对齐资源库的标签下拉）
const allTags = ref<any[]>([])
const loadTags = async () => {
  try {
    const res: any = await comicApi.getComicTags({ tree: false })
    allTags.value = (res.tags || []).filter((t: any) => t.comic_count > 0)
  } catch {
    allTags.value = []
  }
}
const handleTagChange = (e: Event) => {
  const v = (e.target as HTMLSelectElement).value
  comicStore.filterByTag(v === '' ? null : parseInt(v))
  updateUrl()
}

// 当前是否作为首页（Home）内嵌的漫画 tab 存在。
// 内嵌时需在当前路径 '/' 上更新 query（保留 mode 等首页参数，避免整页跳转到 /comics 导致切换 tab 消失）；
// 独立页（/comics）时维持原有跳转到 Comics 路由的行为。
const isEmbedded = computed(() => route.name === 'Home')

// 将当前筛选/排序/分页状态同步到 URL（不产生历史记录）
const updateUrl = () => {
  const query = comicStore.toQuery()
  if (isEmbedded.value) {
    router.replace({ query: { ...route.query, ...query } })
  } else {
    router.replace({ name: 'Comics', query })
  }
}

const loading = computed(() => comicStore.loading)
const comics = computed(() => comicStore.comics)
const libraries = computed(() => comicStore.libraries)

const searchQuery = computed({
  get: () => comicStore.searchQuery,
  set: (v) => comicStore.searchQuery = v
})

const sortOptions = [
  { value: 'recommended', label: '推荐' },
  { value: 'name', label: '名称' },
  { value: 'created_at', label: '添加时间' },
  { value: 'page_count', label: '页数' },
  { value: 'like_count', label: '点赞数' },
  { value: 'favorite_count', label: '收藏数' }
]

// 续读
const continueComics = ref<Comic[]>([])
const loadContinue = async () => {
  try {
    const res: any = await (await import('../api')).comicApi.getComics({ continue: true, limit: 50 })
    continueComics.value = res.comics || []
  } catch {
    continueComics.value = []
  }
}

const handleSortChange = (e: Event) => { comicStore.setSortBy((e.target as HTMLSelectElement).value); updateUrl() }
const handleOrderChange = (e: Event) => { comicStore.setSortOrder((e.target as HTMLSelectElement).value); updateUrl() }
const handleLibraryChange = (e: Event) => {
  const v = (e.target as HTMLSelectElement).value
  comicStore.filterByLibrary(v === '' ? null : parseInt(v))
  updateUrl()
}
const handleComicClick = (c: Comic) => router.push({ name: 'Comic', params: { hash: c.hash } })

// ============ 编辑模式（抽屉编辑单条，对齐视频） ============
const editMode = ref(false)
const editDrawerVisible = ref(false)
const editingItem = ref<any>(null)

const toggleEditMode = () => {
  editMode.value = !editMode.value
}

const openEdit = (c: any) => {
  editingItem.value = c
  editDrawerVisible.value = true
}

const confirmDeleteComic = async (c: Comic) => {
  if (!window.confirm(`确定要将漫画「${c.title}」移入回收站吗？管理员可在回收站中恢复或彻底删除。`)) return
  try {
    const res = await comicApi.deleteComic(c.hash)
    if (res.data.success) {
      ElMessage.success(res.data.message || '已移入回收站')
      comics.value = comics.value.filter(x => x.hash !== c.hash)
    } else {
      ElMessage.error(res.data.message || '删除失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '删除失败')
  }
}

// 正常模式下点击卡片上的 tag → 按该 tag 筛选漫画
const onTagClick = (tag: any) => {
  if (editMode.value) return
  let id = tag.id
  // 通过抽屉新增的标签可能缺少 id，按名称在标签表中回查
  if (id == null && tag.name) {
    const found = allTags.value.find((t: any) => t.name === tag.name)
    if (found) id = found.id
  }
  if (id != null) comicStore.filterByTag(id)
}

// 抽屉保存后就地更新列表中的该条数据
const onEditSaved = (updated: any) => {
  const idx = comicStore.comics.findIndex((c: any) => c.hash === updated.hash)
  if (idx !== -1) {
    comicStore.comics[idx] = { ...comicStore.comics[idx], ...updated }
  }
}

// 分页
const currentPage = computed(() => Math.floor(comicStore.pagination.offset / comicStore.pagination.limit) + 1)
const totalPages = computed(() => Math.ceil(comicStore.pagination.total / comicStore.pagination.limit) || 1)
const goToPage = async (p: number) => {
  if (p < 1 || p > totalPages.value) return
  // 乐观更新高亮，避免等待请求期间页码跳动
  comicStore.pagination.offset = (p - 1) * comicStore.pagination.limit
  // 只更新 URL（page 写入 query），由 route.query 监听负责拉取对应页数据，
  // 避免直接拉取与 updateUrl 触发 watcher 造成的重复请求与页码回退。
  // 始终带上 page 参数，确保切换到第 1 页时 watcher 也能正确触发重新拉取。
  const query = comicStore.toQuery()
  query.page = String(p)
  if (isEmbedded.value) {
    router.push({ query: { ...route.query, ...query } })
  } else {
    router.push({ name: 'Comics', query })
  }
}
const pageRange = computed(() => {
  const cur = currentPage.value, total = totalPages.value
  const range: (number | null)[] = []
  if (total <= 7) {
    for (let i = 1; i <= total; i++) range.push(i)
  } else {
    range.push(1)
    const start = Math.max(2, cur - 1), end = Math.min(total - 1, cur + 1)
    if (start > 2) range.push(null)
    for (let i = start; i <= end; i++) range.push(i)
    if (end < total - 1) range.push(null)
    range.push(total)
  }
  return range
})

let searchTimer: number | null = null
watch(searchQuery, (q) => {
  if (searchTimer) clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => { comicStore.searchComics(q); updateUrl() }, 500)
})

onMounted(async () => {
  // 如果 URL 带 query 参数（刷新/分享链接/前进后退），从其中恢复状态
  if (Object.keys(route.query).length > 0) {
    await Promise.all([
      comicStore.fetchUserLibraries(),
      comicStore.initFromQuery(route.query as Record<string, string>),
      loadContinue(),
      loadTags()
    ])
  } else {
    await Promise.all([
      comicStore.fetchUserLibraries(),
      comicStore.fetchComics(true),
      loadContinue(),
      loadTags()
    ])
  }
})

// 监听路由 query 变化（处理浏览器后退/前进或 URL 直接访问场景）
watch(() => route.query, async (newQuery) => {
  if (Object.keys(newQuery).length === 0) return
  await comicStore.initFromQuery(newQuery as Record<string, string>)
}, { immediate: false })
</script>

<template>
  <div class="comics-container">
    <div class="action-bar">
      <div class="search-box">
        <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
        </svg>
        <input v-model="searchQuery" type="text" placeholder="搜索漫画名称..." class="search-input" />
      </div>
      <div class="sort-box">
        <select class="sort-select" :value="comicStore.sortBy" @change="handleSortChange">
          <option v-for="o in sortOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <select class="sort-order-select" :value="comicStore.sortOrder" @change="handleOrderChange">
          <option value="desc">倒序</option>
          <option value="asc">正序</option>
        </select>
        <select class="library-select" :value="comicStore.selectedLibraryId || ''" @change="handleLibraryChange">
          <option value="">全部资源库</option>
          <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
        </select>
        <select class="library-select tag-select" :value="comicStore.selectedTagId || ''" @change="handleTagChange">
          <option value="">全部标签</option>
          <option v-for="t in allTags" :key="t.id" :value="t.id">{{ t.name }} ({{ t.comic_count }})</option>
        </select>
      </div>
      <button class="batch-toggle-btn" :class="{ active: editMode }" @click="toggleEditMode" title="编辑">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>
        <span class="batch-toggle-text">{{ editMode ? '退出编辑' : '编辑' }}</span>
      </button>
      <div class="view-toggle">
        <button class="view-toggle-btn" :class="{ active: comicStore.viewMode === 'grid' }" @click="comicStore.setViewMode('grid')" title="缩略图">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
          <span>缩略图</span>
        </button>
        <button class="view-toggle-btn" :class="{ active: comicStore.viewMode === 'list' }" @click="comicStore.setViewMode('list')" title="列表">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          <span>列表</span>
        </button>
      </div>
    </div>

    <!-- 继续阅读（默认收起，可点击展开；数量受控） -->
    <div v-if="continueComics.length > 0" class="continue-section">
      <div class="continue-header" :class="{ expanded: continueExpanded }" @click="continueExpanded = !continueExpanded">
        <div class="continue-title">
          <svg class="chev" :class="{ open: continueExpanded }" viewBox="0 0 24 24" width="18" height="18">
            <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <h2 class="section-title">继续阅读</h2>
          <span class="continue-count">{{ continueComics.length }}</span>
        </div>
        <span class="continue-hint">{{ continueExpanded ? '收起' : `展开全部 (${continueComics.length})` }}</span>
      </div>
      <div v-show="continueExpanded" class="comic-grid">
        <ComicCard v-for="c in continueComics.slice(0, CONTINUE_MAX)" :key="c.hash" :comic="c" @click="handleComicClick" />
      </div>
      <p v-if="continueExpanded && continueComics.length > CONTINUE_MAX" class="continue-more">仅显示最近 {{ CONTINUE_MAX }} 本</p>
    </div>

    <div v-if="loading" class="loading-container"><div class="spinner"></div><p>加载中...</p></div>

    <template v-else>
      <div v-if="comics.length > 0" class="comic-section">
        <div v-if="comicStore.viewMode === 'grid'" class="comic-grid">
          <ComicCard
            v-for="c in comics"
            :key="c.hash"
            :comic="c"
            :editable="editMode"
            @click="handleComicClick"
            @edit="openEdit"
            @tag-click="onTagClick"
          />
        </div>
        <div v-else class="comic-list">
          <div v-for="c in comics" :key="c.hash" class="comic-list-row" @click="editMode ? openEdit(c) : handleComicClick(c)">
            <div class="list-thumb" @click.stop="editMode ? openEdit(c) : handleComicClick(c)">
              <img :src="c.cover_url ? (userStore.token ? c.cover_url + '?token=' + userStore.token : c.cover_url) : '/placeholder.jpg'" loading="lazy" @error="(e:any)=>e.target.src='/placeholder.jpg'" />
              <span class="list-pages">{{ c.page_count }}P</span>
            </div>
            <div class="list-info">
              <h3 class="list-title">{{ c.title }}</h3>
              <div class="list-meta"><span>{{ c.page_count }} 页</span><span v-if="c.like_count>0">♥ {{ c.like_count }}</span></div>
            </div>
            <div class="list-actions">
              <button
                v-if="editMode"
                class="list-action-btn edit"
                @click.stop="openEdit(c)"
                title="编辑"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>
              </button>
              <button
                v-if="editMode"
                class="list-action-btn delete"
                @click.stop="confirmDeleteComic(c)"
                title="删除（移入回收站）"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/></svg>
              </button>
              <template v-else>
                <button class="list-action-btn like" :class="{active:c.is_liked}" @click.stop="comicStore.interact(c.hash,'like')">♥</button>
                <button class="list-action-btn favorite" :class="{active:c.is_favorited}" @click.stop="comicStore.interact(c.hash,'favorite')">★</button>
              </template>
            </div>
          </div>
        </div>
      </div>
      <div v-if="comics.length === 0" class="empty-state">
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
        <p>暂无漫画</p>
        <p class="empty-tip" v-if="userStore.isAdmin">在资源库里放入「扁平的图片文件夹」（每本 >=2 张图）即可自动收录。</p>
      </div>

      <div v-if="totalPages > 1" class="pagination">
        <button class="page-btn" :disabled="currentPage===1" @click="goToPage(1)">首页</button>
        <button class="page-btn" :disabled="currentPage===1" @click="goToPage(currentPage-1)">‹ 上一页</button>
        <template v-for="p in pageRange" :key="p">
          <button v-if="p" class="page-btn" :class="{active: p===currentPage}" @click="goToPage(p)">{{ p }}</button>
          <span v-else class="page-ellipsis">...</span>
        </template>
        <button class="page-btn" :disabled="currentPage===totalPages" @click="goToPage(currentPage+1)">下一页 ›</button>
        <button class="page-btn" :disabled="currentPage===totalPages" @click="goToPage(totalPages)">末页</button>
        <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
      </div>
    </template>

    <!-- 编辑抽屉（漫画） -->
    <ItemEditDrawer
      :visible="editDrawerVisible"
      type="comic"
      :item="editingItem"
      @update:visible="editDrawerVisible = $event"
      @saved="onEditSaved"
    />
  </div>
</template>

<style scoped>
.comics-container { padding: 20px; max-width: 1400px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.action-bar { display: flex; gap: 16px; margin-bottom: 24px; align-items: center; flex-wrap: wrap; }
.search-box { flex: 1; max-width: 500px; position: relative; }
.search-icon { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); color: #666; }
.search-input { width: 100%; height: 48px; padding: 0 16px 0 48px; border: 1px solid #333; border-radius: 12px; background: #1a1a1a; color: #fff; font-size: 15px; }
.search-input:focus { outline: none; border-color: #2196F3; box-shadow: 0 0 0 3px rgba(33,150,243,0.1); }
.sort-box { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sort-select, .sort-order-select, .library-select { height: 40px; padding: 0 12px; border: 1px solid #333; border-radius: 8px; background: #1a1a1a; color: #fff; font-size: 14px; cursor: pointer; }
.view-toggle { display: flex; gap: 4px; background: #252525; border: 1px solid #333; border-radius: 8px; padding: 3px; margin-left: auto; }
.view-toggle-btn { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border: none; background: transparent; color: #aaa; font-size: 13px; border-radius: 6px; cursor: pointer; }
.view-toggle-btn.active { background: #2196F3; color: #fff; }
.comic-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
.comic-list { display: flex; flex-direction: column; gap: 8px; }
.comic-list-row { display: flex; align-items: center; gap: 14px; padding: 8px; background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 10px; cursor: pointer; transition: background 0.2s; }
.comic-list-row:hover { background: #222; }
.list-thumb { position: relative; width: 120px; flex-shrink: 0; aspect-ratio: 3/4; overflow: hidden; border-radius: 8px; background: #000; }
.list-thumb img { width: 100%; height: 100%; object-fit: cover; }
.list-pages { position: absolute; bottom: 6px; right: 6px; background: rgba(0,0,0,0.7); color: #fff; padding: 1px 6px; border-radius: 4px; font-size: 11px; }
.list-info { flex: 1; min-width: 0; }
.list-title { font-size: 14px; font-weight: 500; color: #fff; margin: 0 0 6px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.list-meta { display: flex; gap: 14px; font-size: 12px; color: #999; }
.list-actions { display: flex; gap: 6px; }
.list-action-btn { width: 34px; height: 34px; background: #2a2a2a; border: none; border-radius: 50%; color: #aaa; cursor: pointer; }
.list-action-btn.like.active { color: #ff4757; background: rgba(255,71,87,0.15); }
.list-action-btn.favorite.active { color: #ffa502; background: rgba(255,165,2,0.15); }
.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 300px; }
.spinner { width: 48px; height: 48px; border: 3px solid #333; border-top-color: #2196F3; border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.continue-section { margin-bottom: 32px; }
.section-title { font-size: 20px; font-weight: 600; color: #fff; margin: 0 0 16px; }
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; color: #666; }
.empty-state p { margin-top: 12px; font-size: 16px; }
.empty-tip { font-size: 13px; color: #888; max-width: 420px; text-align: center; }
.pagination { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 24px 0; flex-wrap: wrap; }
.batch-toggle-btn { height: 36px; padding: 0 14px; border: 1px solid rgba(33,150,243,0.3); border-radius: 18px; background: rgba(33,150,243,0.1); color: #4a9eff; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.25s; display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.batch-toggle-btn:hover { background: rgba(33,150,243,0.2); }
.batch-toggle-btn.active { background: #2196F3; color: #fff; border-color: #2196F3; }
.batch-toggle-text { letter-spacing: 0.3px; }
.list-action-btn.edit { background: #2196F3; color: #fff; }
.list-action-btn.edit:hover { background: #1e88e5; }
.page-btn { padding: 8px 14px; background: #2a2a2a; color: #ccc; border: 1px solid #444; border-radius: 6px; cursor: pointer; font-size: 14px; }
.page-btn:hover:not(:disabled) { background: #3a3a3a; color: #fff; }
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-btn.active { background: #2196F3; color: #fff; border-color: #2196F3; }
.page-ellipsis { color: #666; padding: 0 4px; }
.page-info { color: #888; font-size: 13px; margin-left: 12px; }
@media (max-width: 1200px) { .comic-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px) { .comic-grid { grid-template-columns: repeat(2, 1fr); } .view-toggle { margin-left: 0; } }
@media (max-width: 600px) {
  .comics-container { padding: 12px; }
  .comic-grid { grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
  .search-box { max-width: 100%; width: 100%; }
  .action-bar { flex-direction: column; align-items: stretch; }
}

/* 继续阅读：默认收起，点击展开，避免遮挡界面 */
.continue-section { margin-bottom: 24px; }
.continue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: #1a1a1a;
  border: 1px solid #2a2a2a;
  border-radius: 10px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}
.continue-header:hover { background: #212121; }
.continue-header.expanded { border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
.continue-title { display: flex; align-items: center; gap: 8px; }
.continue-title .section-title { margin: 0; font-size: 17px; font-weight: 600; color: #fff; }
.continue-count {
  min-width: 20px;
  padding: 1px 7px;
  background: #2196F3;
  color: #fff;
  border-radius: 10px;
  font-size: 12px;
  text-align: center;
}
.chev { color: #aaa; transition: transform 0.2s ease; }
.chev.open { transform: rotate(90deg); }
.continue-hint { color: #888; font-size: 13px; }
.continue-more { margin: 10px 2px 0; color: #666; font-size: 12px; }
.continue-section .comic-grid { margin-top: 14px; }
</style>
