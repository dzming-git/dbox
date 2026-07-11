<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import VideoCard from '../components/VideoCard.vue'
import TagBadge from '../components/TagBadge.vue'
import type { Video, Tag } from '../types'

const router = useRouter()
const route = useRoute()
const videoStore = useVideoStore()

const loading = computed(() => videoStore.loading)
const videos = computed(() => videoStore.videos)
const tags = computed(() => videoStore.tags)
const selectedTagId = computed(() => videoStore.selectedTagId)

// 标签区域折叠状态
const showTagsSection = ref(false)
const searchQuery = computed({
  get: () => videoStore.searchQuery,
  set: (val) => videoStore.searchQuery = val
})

// 标签树导航
const allTagsTree = ref<any[]>([])
const currentTagLevel = ref<any[]>([])
const tagBreadcrumbs = ref<any[]>([])

// 构建标签树
const buildTagTree = (tags: any[]): any[] => {
  const tagMap = new Map<number, any>()
  const rootTags: any[] = []

  tags.forEach(tag => {
    tagMap.set(tag.id, { ...tag, children: [] })
  })

  tags.forEach(tag => {
    const node = tagMap.get(tag.id)!
    if (tag.parent_id && tagMap.has(tag.parent_id)) {
      tagMap.get(tag.parent_id)!.children.push(node)
    } else {
      rootTags.push(node)
    }
  })

  return rootTags
}

// 初始化标签树
const initTagTree = async () => {
  if (tags.value.length > 0 && allTagsTree.value.length === 0) {
    allTagsTree.value = buildTagTree(tags.value)
    currentTagLevel.value = allTagsTree.value
  }
}

// 进入标签层级
const enterTagLevel = (tag: any) => {
  if (tag.children && tag.children.length > 0) {
    currentTagLevel.value = tag.children
    tagBreadcrumbs.value.push({ id: tag.id, name: tag.name, path: tag.path || tag.name })
  }
}

// 返回上级
const goBackTagLevel = () => {
  if (tagBreadcrumbs.value.length === 0) return

  tagBreadcrumbs.value.pop()
  if (tagBreadcrumbs.value.length === 0) {
    currentTagLevel.value = allTagsTree.value
  } else {
    const parentPath = tagBreadcrumbs.value.map(b => b.name).join('/')
    const findLevel = (nodes: any[], path: string): any[] => {
      for (const node of nodes) {
        if ((node.path || node.name) === path && node.children) {
          return node.children
        }
        if (node.children) {
          const found = findLevel(node.children, path)
          if (found) return found
        }
      }
      return null
    }
    const level = findLevel(allTagsTree.value, parentPath)
    currentTagLevel.value = level || allTagsTree.value
  }
}

// 返回根级别
const goToRootLevel = () => {
  tagBreadcrumbs.value = []
  currentTagLevel.value = allTagsTree.value
}

// 点击标签
const handleTagClick = (tag: any) => {
  // 如果有子标签，进入子层级
  if (tag.children && tag.children.length > 0) {
    enterTagLevel(tag)
  } else {
    // 否则选中该标签
    videoStore.filterByTag(tag.id)
    showTagsSection.value = false
    updateUrl()
  }
}

// 点击"全部"标签
const handleClearTag = () => {
  videoStore.filterByTag(null)
  showTagsSection.value = false
  updateUrl()
}

// 监听 showTagsSection 变化，初始化树
watch(showTagsSection, (newVal) => {
  if (newVal) {
    // 每次展开时重新初始化
    allTagsTree.value = buildTagTree(tags.value)
    currentTagLevel.value = allTagsTree.value
    tagBreadcrumbs.value = []
  }
})

// 监听路由 query 变化（处理浏览器后退/URL直接访问场景）
watch(() => route.query, async (newQuery) => {
  // 跳过空 query
  if (Object.keys(newQuery).length === 0) return
  // 如果 query 包含 from，说明是从视频页返回，不需要重新初始化
  if (newQuery.from) return
  // 从 URL 恢复状态
  await videoStore.initFromQuery(newQuery as Record<string, string>)
}, { immediate: false })

// 更新 URL query 参数（不产生历史记录）
const updateUrl = () => {
  const query = videoStore.toQuery()
  // 使用 replace 避免产生过多历史记录
  router.replace({ path: '/', query })
}

// 排序选项
const sortOptions = [
  { value: 'recommended', label: '推荐' },
  { value: 'name', label: '视频名' },
  { value: 'created_at', label: '文件时间' },
  { value: 'view_count', label: '播放量' },
  { value: 'priority', label: '优先级' },
  { value: 'like_count', label: '点赞数' },
  { value: 'download_count', label: '下载数' }
]

const currentSort = computed(() => videoStore.sortBy)
const currentOrder = computed(() => videoStore.sortOrder)

const handleSortChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  videoStore.setSortBy(target.value)
  updateUrl()
}

const handleOrderChange = (event: Event) => {
  const target = event.target as HTMLSelectElement
  videoStore.setSortOrder(target.value)
  updateUrl()
}

onMounted(async () => {
  // 如果 URL 有 query 参数，从其中恢复状态
  if (Object.keys(route.query).length > 0) {
    await Promise.all([
      videoStore.initFromQuery(route.query as Record<string, string>),
      videoStore.fetchTags()
    ])
  } else {
    await Promise.all([
      videoStore.fetchVideos(true),
      videoStore.fetchTags()
    ])
  }
})

// 搜索防抖
let searchTimeout: number | null = null
watch(() => videoStore.searchQuery, (newQuery) => {
  if (searchTimeout) clearTimeout(searchTimeout)
  searchTimeout = window.setTimeout(() => {
    videoStore.searchVideos(newQuery)
    updateUrl()
  }, 500)
})

// 清除搜索
const clearSearch = () => {
  videoStore.clearSearch()
  updateUrl()
}

const handleVideoClick = (video: Video) => {
  // 把当前首页状态编码为 from 参数，视频页返回时使用
  const homeQuery = videoStore.toQuery()
  const fromQuery: Record<string, string> = {}
  if (Object.keys(homeQuery).length > 0) {
    fromQuery.from = btoa(JSON.stringify(homeQuery))
  }
  router.push({ name: 'Video', params: { hash: video.hash }, query: fromQuery })
}

// ============ 分页相关 ============
const currentPage = computed(() => {
  return Math.floor(videoStore.pagination.offset / videoStore.pagination.limit) + 1
})

const totalPages = computed(() => {
  return Math.ceil(videoStore.pagination.total / videoStore.pagination.limit) || 1
})

const goToPage = async (page: number) => {
  if (page < 1 || page > totalPages.value) return
  // 乐观更新高亮，避免等待请求期间页码跳动
  videoStore.pagination.offset = (page - 1) * videoStore.pagination.limit
  // 只更新 URL（page 写入 query），由 route.query 监听负责拉取对应页数据，
  // 避免直接拉取与 updateUrl 触发 watcher 造成的重复请求与页码回退。
  // 始终带上 page 参数，确保切换到第 1 页时 watcher 也能正确触发重新拉取。
  const query = videoStore.toQuery()
  query.page = String(page)
  router.push({ path: '/', query })
}

const prevPage = async () => {
  if (currentPage.value > 1) {
    await goToPage(currentPage.value - 1)
  }
}

const nextPage = async () => {
  if (currentPage.value < totalPages.value) {
    await goToPage(currentPage.value + 1)
  }
}

// 页码显示范围（确保首页和末页常驻）
const pageRange = computed(() => {
  const current = currentPage.value
  const total = totalPages.value
  const range: (number | null)[] = []

  if (total <= 7) {
    // 总页数 <= 7，直接显示所有页码
    for (let i = 1; i <= total; i++) {
      range.push(i)
    }
  } else {
    // 总页数 > 7，显示 [1, ..., start, ..., end, ..., total]
    const start = Math.max(2, current - 1)
    const end = Math.min(total - 1, current + 1)

    range.push(1) // 首页

    if (start > 2) {
      range.push(null) // 省略号
    }

    for (let i = start; i <= end; i++) {
      range.push(i)
    }

    if (end < total - 1) {
      range.push(null) // 省略号
    }

    range.push(total) // 末页
  }

  return range
})

const shuffling = ref(false)

const handleShuffle = async () => {
  shuffling.value = true
  await videoStore.shuffleVideos()
  shuffling.value = false
}

const handleUndo = async () => {
  shuffling.value = true
  await videoStore.undoShuffle()
  shuffling.value = false
}

const hasPreviousVideos = computed(() => videoStore.previousVideos && videoStore.previousVideos.length > 0)

const formatDuration = (seconds?: number): string => {
  if (!seconds) return '00:00'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`
  }
  return `${m}:${s.toString().padStart(2, '0')}`
}
</script>

<template>
  <div class="home-container">
    <!-- 操作栏 - 移到顶部 -->
    <div class="action-bar">
      <div class="search-box">
        <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索视频标题..."
          class="search-input"
        />
        <button v-if="searchQuery" class="clear-search-btn" @click="clearSearch">×</button>
      </div>
      <div class="sort-box">
        <label class="sort-label">排序：</label>
        <select class="sort-select" :value="currentSort" @change="handleSortChange">
          <option v-for="option in sortOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
        <select class="sort-order-select" :value="currentOrder" @change="handleOrderChange">
          <option value="desc">倒序</option>
          <option value="asc">正序</option>
        </select>
        <!-- 换一批按钮 -->
        <button class="shuffle-btn" @click="handleShuffle" :disabled="shuffling" title="换一批">
          <svg class="shuffle-icon" :class="{ spinning: shuffling }" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l4.4-6c.6-.9 1.9-1.4 3-1.1l5.8 1.6"/>
            <path d="M22 6h-1.4c-1.3 0-2.5.6-3.3 1.7l-4.4 6c-.6.9-1.9 1.4-3 1.1l-5.8-1.6"/>
            <path d="M7.5 12L5 8l9 4-2.5 4"/>
            <path d="M16.5 12L19 16l-9-4 2.5-4"/>
          </svg>
          <span class="shuffle-text">{{ shuffling ? '换选中...' : '换一批' }}</span>
        </button>
        <!-- 撤回按钮 -->
        <button v-if="hasPreviousVideos" class="undo-btn" @click="handleUndo" :disabled="shuffling" title="撤回">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M3 10h10c4.4 0 8 3.6 8 8v2"/>
            <path d="M7 6L3 10l4 4"/>
          </svg>
          <span class="undo-text">撤回</span>
        </button>
      </div>
      <div v-if="searchQuery" class="search-status">
        搜索: "{{ searchQuery }}" ({{ videos.length }} 个结果)
      </div>
    </div>

    <!-- 标签筛选按钮 -->
    <div class="tags-toggle-bar">
      <button class="tags-toggle-btn" @click="showTagsSection = !showTagsSection">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M20.59 13.41l-7.17 7.17a2 2 0 0 1-2.83 0L2 12V2h10l8.59 8.59a2 2 0 0 1 0 2.82z"/>
          <line x1="7" y1="7" x2="7.01" y2="7"/>
        </svg>
        {{ showTagsSection ? '收起标签' : '展开标签筛选' }}
        <span v-if="selectedTagId" class="selected-tag-name">
          ({{ tags.find(t => t.id === selectedTagId)?.name || '已选标签' }})
        </span>
      </button>
    </div>

    <!-- 标签区域 - 可折叠 -->
    <div v-if="showTagsSection" class="tags-section">
      <!-- 面包屑导航 -->
      <div class="tag-tree-nav">
        <div class="tag-breadcrumb" v-if="tagBreadcrumbs.length > 0">
          <span class="breadcrumb-root" @click="goToRootLevel">根</span>
          <template v-for="(crumb, idx) in tagBreadcrumbs" :key="crumb.id">
            <span class="breadcrumb-sep">/</span>
            <span
              class="breadcrumb-item"
              :class="{ active: idx === tagBreadcrumbs.length - 1 }"
              @click="goBackTagLevel"
            >{{ crumb.name }}</span>
          </template>
        </div>

        <!-- 返回按钮 -->
        <button
          v-if="tagBreadcrumbs.length > 0"
          class="nav-back-btn"
          @click="goBackTagLevel"
          title="返回上级"
        >
          ‹ 返回
        </button>
      </div>

      <!-- 标签列表 -->
      <div class="tags-container">
        <!-- 全部按钮 -->
        <div
          class="tag-nav-item all-tag"
          :class="{ active: selectedTagId === null }"
          @click="handleClearTag"
        >
          <span class="tag-nav-name">全部</span>
        </div>

        <!-- 当前层级的标签 -->
        <div
          v-for="tag in currentTagLevel"
          :key="tag.id"
          class="tag-nav-item"
          :class="{ active: selectedTagId === tag.id }"
          @click="handleTagClick(tag)"
        >
          <span class="tag-nav-name">{{ tag.name }}</span>
          <span v-if="tag.children && tag.children.length > 0" class="tag-nav-badge">
            {{ tag.children.length }}
            <span class="tag-nav-arrow">›</span>
          </span>
        </div>

        <p v-if="currentTagLevel.length === 0" class="no-tags">该分类下暂无标签</p>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 视频网格 - 所有视频统一显示 -->
    <template v-else>
      <div v-if="videos.length > 0" class="video-section">
        <div class="video-grid">
          <VideoCard
            v-for="video in videos"
            :key="video.hash"
            :video="video"
            @click="handleVideoClick(video)"
          />
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="videos.length === 0" class="empty-state">
        <svg width="80" height="80" viewBox="0 0 24 24" fill="none" stroke="#666" stroke-width="1">
          <rect x="2" y="4" width="20" height="16" rx="2"/>
          <path d="M10 9l5 3-5 3V9z"/>
        </svg>
        <p>暂无视频</p>
      </div>

      <!-- 分页组件 -->
      <div v-if="totalPages > 1" class="pagination">
        <button class="page-btn" :disabled="currentPage === 1" @click="goToPage(1)">
          首页
        </button>
        <button class="page-btn" :disabled="currentPage === 1" @click="prevPage">
          ‹ 上一页
        </button>
        <template v-for="page in pageRange" :key="page">
          <button
            v-if="page"
            class="page-btn"
            :class="{ active: page === currentPage }"
            @click="goToPage(page)"
          >
            {{ page }}
          </button>
          <span v-else class="page-ellipsis">...</span>
        </template>
        <button class="page-btn" :disabled="currentPage === totalPages" @click="nextPage">
          下一页 ›
        </button>
        <button class="page-btn" :disabled="currentPage === totalPages" @click="goToPage(totalPages)">
          末页
        </button>
        <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 页</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.home-container {
  padding: 20px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* 标签区域 */
.tags-section {
  margin-bottom: 16px;
  background: #1a1a1a;
  border-radius: 12px;
  padding: 12px 16px;
}

.tags-header {
  margin-bottom: 12px;
}

.tags-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #fff;
  margin: 0;
}

/* 标签树导航 */
.tag-tree-nav {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.tag-breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}

.breadcrumb-root {
  color: #4FC3F7;
  cursor: pointer;
}

.breadcrumb-root:hover {
  text-decoration: underline;
}

.breadcrumb-sep {
  color: #555;
}

.breadcrumb-item {
  color: #ccc;
  cursor: pointer;
}

.breadcrumb-item:hover {
  color: #fff;
}

.breadcrumb-item.active {
  color: #4FC3F7;
  cursor: default;
}

.nav-back-btn {
  background: #333;
  border: none;
  color: #888;
  font-size: 13px;
  padding: 6px 12px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav-back-btn:hover {
  background: #444;
  color: #fff;
}

.tags-container {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

/* 标签导航项 */
.tag-nav-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  background: #252525;
  border: 1px solid #333;
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
}

.tag-nav-item:hover {
  background: #333;
  border-color: #444;
}

.tag-nav-item.active {
  background: #2196F3;
  border-color: #2196F3;
}

.tag-nav-item.all-tag {
  background: #333;
}

.tag-nav-name {
  font-size: 13px;
  color: #ccc;
}

.tag-nav-item.active .tag-nav-name {
  color: #fff;
}

.tag-nav-badge {
  display: flex;
  align-items: center;
  gap: 2px;
  font-size: 11px;
  color: #888;
  background: #1a1a1a;
  padding: 2px 6px;
  border-radius: 10px;
}

.tag-nav-arrow {
  font-size: 12px;
  font-weight: bold;
}

.no-tags {
  color: #666;
  font-size: 13px;
  text-align: center;
  padding: 12px;
  width: 100%;
}

/* 标签筛选折叠按钮 */
.tags-toggle-bar {
  margin-bottom: 16px;
}

.tags-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: #252525;
  border: 1px solid #333;
  border-radius: 8px;
  color: #aaa;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.tags-toggle-btn:hover {
  background: #333;
  color: #fff;
  border-color: #444;
}

.selected-tag-name {
  color: #2196F3;
  font-weight: 500;
}

/* 操作栏 */
.action-bar {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
  align-items: center;
  flex-wrap: wrap;
}

/* 排序选择器 */
.sort-box {
  display: flex;
  align-items: center;
  gap: 8px;
}

.sort-label {
  color: #aaa;
  font-size: 14px;
}

.sort-select {
  height: 40px;
  padding: 0 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #1a1a1a;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.2s;
}

.sort-select:hover {
  border-color: #4a9eff;
}

.sort-select:focus {
  outline: none;
  border-color: #4a9eff;
  box-shadow: 0 0 0 2px rgba(74, 158, 255, 0.2);
}

.sort-order-select {
  height: 40px;
  padding: 0 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #1a1a1a;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.2s;
  margin-left: 8px;
}

.sort-order-select:hover {
  border-color: #4a9eff;
}

.sort-order-select:focus {
  outline: none;
  border-color: #4a9eff;
  box-shadow: 0 0 0 2px rgba(74, 158, 255, 0.2);
}

/* 换一批按钮 */
.shuffle-btn {
  height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(74, 158, 255, 0.3);
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(74, 158, 255, 0.15) 0%, rgba(74, 158, 255, 0.05) 100%);
  color: #4a9eff;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.shuffle-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(74, 158, 255, 0.25) 0%, rgba(74, 158, 255, 0.15) 100%);
  border-color: #4a9eff;
  box-shadow: 0 0 20px rgba(74, 158, 255, 0.2);
  transform: translateY(-1px);
}

.shuffle-btn:active:not(:disabled) {
  transform: scale(0.96) translateY(0);
}

.shuffle-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.shuffle-icon {
  flex-shrink: 0;
  transition: transform 0.3s ease;
}

.shuffle-icon.spinning {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.shuffle-text {
  letter-spacing: 0.3px;
}

/* 撤回按钮 */
.undo-btn {
  height: 36px;
  padding: 0 14px;
  border: 1px solid rgba(250, 173, 20, 0.3);
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(250, 173, 20, 0.15) 0%, rgba(250, 173, 20, 0.05) 100%);
  color: #faad14;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
}

.undo-btn:hover:not(:disabled) {
  background: linear-gradient(135deg, rgba(250, 173, 20, 0.25) 0%, rgba(250, 173, 20, 0.15) 100%);
  border-color: #faad14;
  box-shadow: 0 0 20px rgba(250, 173, 20, 0.2);
  transform: translateY(-1px);
}

.undo-btn:active:not(:disabled) {
  transform: scale(0.96) translateY(0);
}

.undo-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.undo-text {
  letter-spacing: 0.3px;
}

.search-box {
  flex: 1;
  max-width: 500px;
  position: relative;
}

.search-icon {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
  color: #666;
}

.search-input {
  width: 100%;
  height: 48px;
  padding: 0 16px 0 48px;
  border: 1px solid #333;
  border-radius: 12px;
  background: #1a1a1a;
  color: #fff;
  font-size: 15px;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.search-input:focus {
  outline: none;
  border-color: #2196F3;
  box-shadow: 0 0 0 3px rgba(33, 150, 243, 0.1);
}

.search-input::placeholder {
  color: #666;
}

.clear-search-btn {
  position: absolute;
  right: 12px;
  top: 50%;
  transform: translateY(-50%);
  background: #333;
  border: none;
  border-radius: 50%;
  width: 20px;
  height: 20px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
}

.clear-search-btn:hover {
  background: #444;
}

.search-status {
  padding: 8px 16px;
  background: #1a1a1a;
  border-radius: 8px;
  color: #888;
  font-size: 14px;
}

/* 加载中 */
.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

.spinner {
  width: 48px;
  height: 48px;
  border: 3px solid #333;
  border-top-color: #2196F3;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 视频网格 */
.video-section {
  margin-bottom: 32px;
  width: 100%;
  max-width: 100%;
  overflow: hidden;
}

.video-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 400px;
  color: #666;
}

.empty-state p {
  margin-top: 16px;
  font-size: 16px;
}


/* 滚动自动加载提示 */
.loading-more {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 20px;
  color: #888;
}

.loading-more p {
  margin: 0;
  font-size: 14px;
}

.spinner-small {
  width: 20px;
  height: 20px;
  border: 2px solid #333;
  border-top-color: #2196F3;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 分页组件 */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px 0;
  flex-wrap: wrap;
}

.page-btn {
  padding: 8px 14px;
  background: #2a2a2a;
  color: #ccc;
  border: 1px solid #444;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) {
  background: #3a3a3a;
  color: #fff;
}

.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.page-btn.active {
  background: #2196F3;
  color: #fff;
  border-color: #2196F3;
}

.page-ellipsis {
  color: #666;
  padding: 0 4px;
}

.page-info {
  color: #888;
  font-size: 13px;
  margin-left: 12px;
}

/* 响应式 */
@media (max-width: 1200px) {
  .video-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 900px) {
  .video-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 600px) {
  .home-container {
    padding: 12px;
    max-width: 100vw;
  }
  
  /* 移动端两列布局 */
  .video-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    width: 100%;
  }
  
  .section-title {
    font-size: 18px;
  }
  
  .tags-section {
    padding: 12px;
    max-width: 100%;
  }
  
  .tags-container {
    max-width: 100%;
  }
  
  .action-bar {
    max-width: 100%;
  }
  
  .search-box {
    max-width: 100%;
  }
  
  .search-input {
    height: 44px;
    font-size: 14px;
  }

  /* 移动端换一批按钮 */
  .shuffle-btn {
    height: 32px;
    padding: 0 10px;
    font-size: 12px;
    gap: 4px;
  }

  .shuffle-btn svg {
    width: 14px;
    height: 14px;
  }

  .undo-btn {
    height: 32px;
    padding: 0 10px;
    font-size: 12px;
    gap: 4px;
  }

  .undo-btn svg {
    width: 14px;
    height: 14px;
  }
}
</style>
