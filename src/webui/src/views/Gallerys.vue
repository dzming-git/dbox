<script setup lang="ts">
defineOptions({ name: 'Gallerys' })
import { ref, onMounted, computed, watch, onActivated, onDeactivated } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useGalleryStore } from '../stores/galleryStore'
import { useUserStore } from '../stores/userStore'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import GalleryCard from '../components/GalleryCard.vue'
import ResourceListRow from '../components/ResourceListRow.vue'
import type { Gallery } from '../types'
import { galleryApi } from '../api'
import { withThumbToken } from '../utils/media'

const router = useRouter()
const route = useRoute()
const galleryStore = useGalleryStore()
const userStore = useUserStore()

// 标签筛选（对齐资源库的标签下拉）
const allTags = ref<any[]>([])
const loadTags = async () => {
  try {
    const res: any = await galleryApi.getGalleryTags({ tree: false })
    allTags.value = (res.tags || []).filter((t: any) => t.gallery_count > 0)
  } catch {
    allTags.value = []
  }
}
const handleTagChange = (e: Event) => {
  const v = (e.target as HTMLSelectElement).value
  galleryStore.filterByTag(v === '' ? null : parseInt(v))
  updateUrl()
}

const galleryListMeta = (g: Gallery): string[] => {
  const meta = [`${g.page_count} 页`]
  if (g.like_count > 0) meta.push(`♥ ${g.like_count}`)
  return meta
}

// 当前是否作为首页（Home）内嵌的图集 tab 存在。
// 内嵌时需在当前路径 '/' 上更新 query（保留 mode 等首页参数，避免整页跳转到 /galleries 导致切换 tab 消失）；
// 独立页（/galleries）时维持原有跳转到 Gallerys 路由的行为。
const isEmbedded = computed(() => route.name === 'Home')

// 将当前筛选/排序/分页状态同步到 URL（不产生历史记录）
const updateUrl = () => {
  const query = galleryStore.toQuery()
  if (isEmbedded.value) {
    router.replace({ query: { ...route.query, ...query } })
  } else {
    router.replace({ name: 'Gallerys', query })
  }
}

const loading = computed(() => galleryStore.loading)
const galleries = computed(() => galleryStore.galleries)
const libraries = computed(() => galleryStore.libraries)

// 返回顶部：把上次在详情页查看过的图集置顶到随机推荐第一个
const displayGallerys = computed(() => {
  const list = [...galleries.value]
  try {
    const last = sessionStorage.getItem('lastViewedGallery')
    if (last) {
      const idx = list.findIndex((c) => c.hash === last)
      if (idx > 0) {
        const [item] = list.splice(idx, 1)
        list.unshift(item)
      } else if (idx === 0) {
        // 已经在第一位，无需调整
      }
      sessionStorage.removeItem('lastViewedGallery')
    }
  } catch {}
  return list
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
const continueGallerys = ref<Gallery[]>([])
const loadContinue = async () => {
  try {
    const res: any = await (await import('../api')).galleryApi.getGallerys({ continue: true, limit: 50 })
    continueGallerys.value = res.galleries || []
  } catch {
    continueGallerys.value = []
  }
}

const handleSortChange = (e: Event) => { galleryStore.setSortBy((e.target as HTMLSelectElement).value); updateUrl() }
const handleOrderChange = (e: Event) => { galleryStore.setSortOrder((e.target as HTMLSelectElement).value); updateUrl() }
const handleLibraryChange = (e: Event) => {
  const v = (e.target as HTMLSelectElement).value
  galleryStore.filterByLibrary(v === '' ? null : parseInt(v))
  updateUrl()
}
const handleGalleryClick = (c: Gallery) => router.push({ name: 'Gallery', params: { hash: c.hash } })

// 正常模式下点击卡片上的 tag → 按该 tag 筛选图集
const onTagClick = (tag: any) => {
  let id = tag.id
  // 通过抽屉新增的标签可能缺少 id，按名称在标签表中回查
  if (id == null && tag.name) {
    const found = allTags.value.find((t: any) => t.name === tag.name)
    if (found) id = found.id
  }
  if (id != null) galleryStore.filterByTag(id)
}

// 分页
const currentPage = computed(() => Math.floor(galleryStore.pagination.offset / galleryStore.pagination.limit) + 1)
const totalPages = computed(() => Math.ceil(galleryStore.pagination.total / galleryStore.pagination.limit) || 1)
const goToPage = async (p: number) => {
  if (p < 1 || p > totalPages.value) return
  // 乐观更新高亮，避免等待请求期间页码跳动
  galleryStore.pagination.offset = (p - 1) * galleryStore.pagination.limit
  // 只更新 URL（page 写入 query），由 route.query 监听负责拉取对应页数据，
  // 避免直接拉取与 updateUrl 触发 watcher 造成的重复请求与页码回退。
  // 始终带上 page 参数，确保切换到第 1 页时 watcher 也能正确触发重新拉取。
  const query = galleryStore.toQuery()
  query.page = String(p)
  if (isEmbedded.value) {
    router.push({ query: { ...route.query, ...query } })
  } else {
    router.push({ name: 'Gallerys', query })
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

onMounted(async () => {
  // 如果 URL 带 query 参数（刷新/分享链接/前进后退），从其中恢复状态
  if (Object.keys(route.query).length > 0) {
    await Promise.all([
      galleryStore.fetchUserLibraries(),
      galleryStore.initFromQuery(route.query as Record<string, string>),
      loadContinue(),
      loadTags()
    ])
  } else {
    await Promise.all([
      galleryStore.fetchUserLibraries(),
      galleryStore.fetchGallerys(true),
      loadContinue(),
      loadTags()
    ])
  }
})

// 顶部下拉刷新：仅作为独立路由（/galleries）时注册，嵌入首页时不接管手势
const ptr = usePullToRefresh()
function registerPtr() {
  if (route.name !== 'Gallerys') return
  ptr.setHandler(() => galleryStore.fetchGallerys(true))
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())

// 监听路由 query 变化（处理浏览器后退/前进或 URL 直接访问场景）
watch(() => route.query, async (newQuery) => {
  if (Object.keys(newQuery).length === 0) return
  await galleryStore.initFromQuery(newQuery as Record<string, string>)
}, { immediate: false })
</script>

<template>
  <div class="galleries-container">
    <div class="action-bar">
      <div class="sort-box">
        <select class="sort-select" :value="galleryStore.sortBy" @change="handleSortChange">
          <option v-for="o in sortOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <select class="sort-order-select" :value="galleryStore.sortOrder" @change="handleOrderChange">
          <option value="desc">倒序</option>
          <option value="asc">正序</option>
        </select>
        <select class="library-select" :value="galleryStore.selectedLibraryId || ''" @change="handleLibraryChange">
          <option value="">全部资源库</option>
          <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
        </select>
        <select class="library-select tag-select" :value="galleryStore.selectedTagId || ''" @change="handleTagChange">
          <option value="">全部标签</option>
          <option v-for="t in allTags" :key="t.id" :value="t.id">{{ t.name }} ({{ t.gallery_count }})</option>
        </select>
      </div>
      <div class="view-toggle">
        <button class="view-toggle-btn" :class="{ active: galleryStore.viewMode === 'grid' }" @click="galleryStore.setViewMode('grid')" title="缩略图">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
          <span>缩略图</span>
        </button>
        <button class="view-toggle-btn" :class="{ active: galleryStore.viewMode === 'list' }" @click="galleryStore.setViewMode('list')" title="列表">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
          <span>列表</span>
        </button>
      </div>
    </div>

    <!-- 继续阅读（默认收起，可点击展开；数量受控） -->
    <div v-if="continueGallerys.length > 0" class="continue-section">
      <div class="continue-header" :class="{ expanded: continueExpanded }" @click="continueExpanded = !continueExpanded">
        <div class="continue-title">
          <svg class="chev" :class="{ open: continueExpanded }" viewBox="0 0 24 24" width="18" height="18">
            <path d="M9 6l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <h2 class="section-title">继续阅读</h2>
          <span class="continue-count">{{ continueGallerys.length }}</span>
        </div>
        <span class="continue-hint">{{ continueExpanded ? '收起' : `展开全部 (${continueGallerys.length})` }}</span>
      </div>
      <div v-show="continueExpanded" class="gallery-grid">
        <GalleryCard v-for="c in continueGallerys.slice(0, CONTINUE_MAX)" :key="c.hash" :gallery="c" @click="handleGalleryClick" />
      </div>
      <p v-if="continueExpanded && continueGallerys.length > CONTINUE_MAX" class="continue-more">仅显示最近 {{ CONTINUE_MAX }} 本</p>
    </div>

    <div v-if="loading" class="loading-container"><div class="spinner"></div><p>加载中...</p></div>

    <template v-else>
      <div v-if="galleries.length > 0" class="gallery-section">
        <div v-if="galleryStore.viewMode === 'grid'" class="gallery-grid">
          <GalleryCard
            v-for="c in displayGallerys"
            :key="c.hash"
            :gallery="c"
            @click="handleGalleryClick"
            @tag-click="onTagClick"
          />
        </div>
        <div v-else class="gallery-list">
          <ResourceListRow
            v-for="c in displayGallerys"
            :key="c.hash"
            type="gallery"
            :item="c"
            :thumb-url="c.cover_url ? withThumbToken(c.cover_url) : '/placeholder.jpg'"
            :meta="galleryListMeta(c)"
            :badge="c.page_count + 'P'"
            :edit-mode="false"
            @click="handleGalleryClick"
          />
        </div>
      </div>
      <div v-if="galleries.length === 0" class="empty-state">
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
        <p>暂无图集</p>
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

      <!-- 移动端单手翻页：底部悬浮的上一页 / 下一页 -->
      <div v-if="totalPages > 1" class="mobile-pager">
        <button class="page-btn mobile-page-btn" :disabled="currentPage===1" @click="goToPage(currentPage-1)">‹ 上一页</button>
        <span class="mobile-page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
        <button class="page-btn mobile-page-btn" :disabled="currentPage===totalPages" @click="goToPage(currentPage+1)">下一页 ›</button>
      </div>
    </template>
  </div>
</template>

<style scoped>
.galleries-container { padding: 20px; max-width: 1400px; margin: 0 auto; width: 100%; box-sizing: border-box; }
.action-bar { display: flex; gap: 16px; margin-bottom: 24px; align-items: center; flex-wrap: wrap; }
.sort-box { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sort-select, .sort-order-select, .library-select { height: 40px; padding: 0 12px; border: 1px solid var(--border-default); border-radius: 8px; background: var(--bg-surface); color: var(--text-primary); font-size: 14px; cursor: pointer; }
.view-toggle { display: flex; gap: 4px; background: var(--bg-surface-hover); border: 1px solid var(--border-default); border-radius: 8px; padding: 3px; margin-left: auto; }
.view-toggle-btn { display: flex; align-items: center; gap: 6px; padding: 6px 12px; border: none; background: transparent; color: var(--text-secondary); font-size: 13px; border-radius: 6px; cursor: pointer; }
.view-toggle-btn.active { background: var(--accent); color: var(--text-on-accent); }
.gallery-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; }
.gallery-list { display: flex; flex-direction: column; gap: 8px; }
.list-actions { display: flex; gap: 6px; }
.list-action-btn { width: 34px; height: 34px; background: var(--bg-surface-hover); border: none; border-radius: 50%; color: var(--text-secondary); cursor: pointer; }
.list-action-btn.like.active { color: #ff4757; background: rgba(255,71,87,0.15); }
.list-action-btn.favorite.active { color: #ffa502; background: rgba(255,165,2,0.15); }
.loading-container { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 300px; }
.spinner { width: 48px; height: 48px; border: 3px solid var(--border-default); border-top-color: var(--accent); border-radius: 50%; animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.continue-section { margin-bottom: 32px; }
.section-title { font-size: 20px; font-weight: 600; color: var(--text-primary); margin: 0 0 16px; }
.empty-state { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 400px; color: var(--text-tertiary); }
.empty-state p { margin-top: 12px; font-size: 16px; }
.empty-tip { font-size: 13px; color: var(--text-secondary); max-width: 420px; text-align: center; }
.pagination { display: flex; align-items: center; justify-content: center; gap: 8px; padding: 24px 0; flex-wrap: wrap; }
.mobile-pager { display: none; }
.batch-toggle-btn { height: 36px; padding: 0 14px; border: 1px solid rgba(33,150,243,0.3); border-radius: 18px; background: rgba(33,150,243,0.1); color: #4a9eff; font-size: 13px; font-weight: 500; cursor: pointer; transition: all 0.25s; display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.batch-toggle-btn:hover { background: rgba(33,150,243,0.2); }
.batch-toggle-btn.active { background: var(--accent); color: var(--text-on-accent); border-color: var(--accent); }
.batch-toggle-text { letter-spacing: 0.3px; }
.list-action-btn.edit { background: var(--accent); color: var(--text-on-accent); }
.list-action-btn.edit:hover { background: var(--accent); }
.list-action-btn.delete { background: var(--bg-surface-hover); color: var(--danger); }
.list-action-btn.delete:hover { background: rgba(255,107,107,0.18); color: #ff5252; }
.page-btn { padding: 8px 14px; background: var(--bg-surface-hover); color: var(--text-secondary); border: 1px solid var(--border-strong); border-radius: 6px; cursor: pointer; font-size: 14px; }
.page-btn:hover:not(:disabled) { background: var(--bg-surface-hover); color: var(--accent); }
.page-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.page-btn.active { background: var(--accent); color: var(--text-on-accent); border-color: var(--accent); }
.page-ellipsis { color: var(--text-tertiary); padding: 0 4px; }
.page-info { color: var(--text-secondary); font-size: 13px; margin-left: 12px; }
@media (max-width: 1200px) { .gallery-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px) { .gallery-grid { grid-template-columns: repeat(2, 1fr); } .view-toggle { margin-left: 0; } }
@media (max-width: 600px) {
  .galleries-container { padding: 12px; }
  .gallery-grid { grid-template-columns: repeat(2, minmax(0,1fr)); gap: 12px; }
  .action-bar { flex-direction: column; align-items: stretch; }
  .view-toggle { margin-left: 0; width: 100%; }
  .view-toggle-btn { flex: 1; justify-content: center; }
  .gallery-section { padding-bottom: 76px; }
  .mobile-pager {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    position: fixed;
    left: 0; right: 0; bottom: 0;
    padding: 10px 16px calc(10px + env(safe-area-inset-bottom));
    background: var(--nav-bg);
    backdrop-filter: saturate(180%) blur(20px);
    -webkit-backdrop-filter: saturate(180%) blur(20px);
    border-top: 1px solid var(--border-subtle);
    z-index: 50;
  }
  .mobile-page-btn { flex: 1; height: 44px; border-radius: 22px; font-size: 14px; }
  .mobile-page-info { color: var(--text-secondary); font-size: 13px; white-space: nowrap; }
}

/* 继续阅读：默认收起，点击展开，避免遮挡界面 */
.continue-section { margin-bottom: 24px; }
.continue-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}
.continue-header:hover { background: var(--bg-surface-hover); }
.continue-header.expanded { border-bottom-left-radius: 0; border-bottom-right-radius: 0; }
.continue-title { display: flex; align-items: center; gap: 8px; }
.continue-title .section-title { margin: 0; font-size: 17px; font-weight: 600; color: var(--text-primary); }
.continue-count {
  min-width: 20px;
  padding: 1px 7px;
  background: var(--accent);
  color: var(--text-on-accent);
  border-radius: 10px;
  font-size: 12px;
  text-align: center;
}
.chev { color: var(--text-secondary); transition: transform 0.2s ease; }
.chev.open { transform: rotate(90deg); }
.continue-hint { color: var(--text-secondary); font-size: 13px; }
.continue-more { margin: 10px 2px 0; color: var(--text-tertiary); font-size: 12px; }
.continue-section .gallery-grid { margin-top: 14px; }
</style>