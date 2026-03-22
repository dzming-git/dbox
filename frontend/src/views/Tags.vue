<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useVideoStore } from '../stores/videoStore'
import { tagApi } from '../api'
import type { Tag } from '../types'

const videoStore = useVideoStore()

const loading = computed(() => videoStore.loading)

// 所有标签列表
const allTagsList = ref<Tag[]>([])
const searchQuery = ref('')
const expandedTags = ref<Set<number>>(new Set())

// 获取所有标签
const fetchAllTags = async () => {
  try {
    const response = await tagApi.getAllTags() as any
    if (response.success && response.tags) {
      allTagsList.value = response.tags
    }
  } catch (e) {
    console.error('获取标签失败:', e)
  }
}

// 获取标签的子标签
const getChildren = (parentId: number): Tag[] => {
  return allTagsList.value.filter(t => t.parent_id === parentId)
}

// 获取顶级标签
const getRootTags = (): Tag[] => {
  return allTagsList.value.filter(t => !t.parent_id)
}

// 统计视频数量（含子标签）
const countAllVideos = (tag: Tag): number => {
  let count = tag.video_count || 0
  const children = getChildren(tag.id)
  for (const child of children) {
    count += countAllVideos(child)
  }
  return count
}

// 筛选后的标签（扁平，用于搜索）
const filteredTags = computed(() => {
  if (!searchQuery.value) return allTagsList.value
  const query = searchQuery.value.toLowerCase()
  return allTagsList.value.filter(tag =>
    tag.name.toLowerCase().includes(query) ||
    (tag.category && tag.category.toLowerCase().includes(query))
  )
})

// 树形展示的数据（扁平结构，用于渲染）
const displayTags = computed(() => {
  const result: { tag: Tag; level: number }[] = []
  
  const addTags = (tags: Tag[], level: number) => {
    for (const tag of tags) {
      result.push({ tag, level })
      // 如果展开且有子标签，递归添加
      if (expandedTags.value.has(tag.id)) {
        const children = getChildren(tag.id)
        if (children.length > 0) {
          addTags(children, level + 1)
        }
      }
    }
  }
  
  // 根标签
  const rootTags = getRootTags()
  addTags(rootTags, 0)
  
  // 如果有搜索，过滤结果
  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase()
    const filtered = filteredTags.value
    const filteredIds = new Set(filtered.map(t => t.id))
    
    // 包含搜索结果的标签及其父级
    const result2: { tag: Tag; level: number }[] = []
    const addedIds = new Set<number>()
    
    const addWithParents = (tag: Tag, level: number) => {
      if (addedIds.has(tag.id)) return
      addedIds.add(tag.id)
      result2.unshift({ tag, level })
      
      // 找到父标签
      if (tag.parent_id) {
        const parent = allTagsList.value.find(t => t.id === tag.parent_id)
        if (parent) {
          // 找到父级的层级
          let parentLevel = level - 1
          addWithParents(parent, parentLevel)
        }
      }
    }
    
    for (const ft of filtered) {
      addWithParents(ft, 0)
    }
    
    // 重新排序并设置正确的层级
    return result2.map(item => ({
      ...item,
      level: item.level
    })).sort((a, b) => a.tag.id - b.tag.id)
  }
  
  return result
})

onMounted(async () => {
  await fetchAllTags()
})

// 展开/收起
const toggleExpand = (tagId: number) => {
  if (expandedTags.value.has(tagId)) {
    expandedTags.value.delete(tagId)
  } else {
    expandedTags.value.add(tagId)
  }
}

// 获取父标签名称
const getParentName = (parentId: number | null | undefined): string => {
  if (!parentId) return '顶级标签'
  const parent = allTagsList.value.find(t => t.id === parentId)
  return parent?.name || '顶级标签'
}


// 查看标签下的视频 - 跳转到首页并筛选该标签
import { useRouter } from 'vue-router'

const router = useRouter()

const viewTagVideos = (tag: Tag) => {
  router.push({ path: '/', query: { tag: tag.path || tag.name } })
}
</script>

<template>
  <div class="tags-page">
    <div class="page-header">
      <h1 class="page-title">标签管理</h1>
      <p class="page-desc">标签在视频中使用时自动创建，无需手动管理</p>
    </div>

    <!-- 搜索 -->
    <div class="toolbar">
      <div class="search-box">
        <svg class="search-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="8"/>
          <path d="M21 21l-4.35-4.35"/>
        </svg>
        <input
          v-model="searchQuery"
          type="text"
          placeholder="搜索标签..."
          class="search-input"
        />
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 标签树 - 扁平列表方式 -->
    <div v-else class="tags-tree">
      <template v-for="item in displayTags" :key="item.tag.id">
        <div 
          class="tag-row"
          :class="{ 'level-0': item.level === 0, 'level-1': item.level === 1, 'level-2': item.level === 2, 'level-3': item.level >= 3 }"
          :style="{ '--level': item.level }"
        >
          <!-- 缩进占位 -->
          <div class="indent" :style="{ width: item.level * 24 + 'px' }"></div>
          
          <!-- 连接线 -->
          <div v-if="item.level > 0" class="connector">
            <span class="connector-line"></span>
          </div>
          
          <!-- 展开/收起按钮 -->
          <button 
            v-if="getChildren(item.tag.id).length > 0"
            class="expand-btn"
            @click="toggleExpand(item.tag.id)"
          >
            <svg 
              width="16" 
              height="16" 
              viewBox="0 0 24 24" 
              fill="currentColor"
              :class="{ rotated: expandedTags.has(item.tag.id) }"
            >
              <path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z"/>
            </svg>
          </button>
          <div v-else class="expand-placeholder"></div>
          
          <!-- 标签信息 -->
          <div class="tag-content">
            <div class="tag-header">
              <span class="tag-name">{{ item.tag.name }}</span>
              <span v-if="item.tag.category" class="tag-category">{{ item.tag.category }}</span>
              <span class="level-badge" v-if="item.level > 0">Lv.{{ item.level + 1 }}</span>
            </div>
            <div class="tag-meta">
              <span class="tag-count">{{ countAllVideos(item.tag) }} 个视频</span>
              <span v-if="getChildren(item.tag.id).length > 0" class="tag-children-count">
                {{ getChildren(item.tag.id).length }} 个子标签
              </span>
            </div>
          </div>
          
          <!-- 操作按钮 - 只保留查看视频列表 -->
          <div class="tag-actions">
            <button 
              class="action-icon-btn view" 
              @click="viewTagVideos(item.tag)"
              title="查看视频"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/>
              </svg>
            </button>
          </div>
        </div>
      </template>

      <!-- 空状态 -->
      <div v-if="displayTags.length === 0" class="empty-state">
        <p v-if="searchQuery">没有找到匹配的标签</p>
        <p v-else>暂无标签，在视频中添加标签后会自动显示</p>
      </div>
    </div>

  </div>
</template>

<style scoped>
.tags-page {
  padding: 24px;
  max-width: 1200px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.page-title {
  font-size: 28px;
  font-weight: 600;
  color: #fff;
  margin: 0;
}

.page-desc {
  font-size: 14px;
  color: #888;
  margin: 0;
}

.create-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.create-btn:hover {
  background: #1976D2;
}

.toolbar {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.search-box {
  flex: 1;
  max-width: 400px;
  position: relative;
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: #666;
}

.search-input {
  width: 100%;
  height: 44px;
  padding: 0 16px 0 44px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #1a1a1a;
  color: #fff;
  font-size: 14px;
}

.search-input:focus {
  outline: none;
  border-color: #2196F3;
}

.loading-container {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 300px;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #333;
  border-top-color: #2196F3;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 树形结构 - 扁平列表方式 */
.tags-tree {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tag-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 12px 16px;
  background: #1a1a1a;
  border-radius: 8px;
  transition: all 0.2s;
}

.tag-row:hover {
  background: #252525;
}

.tag-row:hover .tag-actions {
  opacity: 1;
}

/* 层级样式 */
.tag-row.level-0 {
  background: #1e3a5f;
}

.tag-row.level-1 {
  background: #1a2a2a;
}

.tag-row.level-2 {
  background: #1a1a2a;
}

.tag-row.level-3 {
  background: #2a1a1a;
}

.indent {
  flex-shrink: 0;
}

.connector {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 24px;
  flex-shrink: 0;
}

.connector-line {
  width: 2px;
  height: 100%;
  background: #444;
}

.expand-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: transparent;
  border: none;
  color: #999;
  cursor: pointer;
  transition: transform 0.2s;
  flex-shrink: 0;
}

.expand-btn svg {
  transition: transform 0.2s;
}

.expand-btn svg.rotated {
  transform: rotate(90deg);
}

.expand-placeholder {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.tag-content {
  flex: 1;
  min-width: 0;
}

.tag-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  flex-wrap: wrap;
}

.tag-name {
  font-size: 15px;
  font-weight: 500;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}

.level-badge {
  font-size: 10px;
  color: #888;
  background: #333;
  padding: 2px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}

.tag-category {
  font-size: 12px;
  color: #888;
  background: #333;
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
  white-space: nowrap;
}

.tag-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: #999;
}

.tag-children-count {
  color: #2196F3;
}

.tag-actions {
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.2s;
}

.action-icon-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  background: transparent;
  border: none;
  border-radius: 6px;
  color: #999;
  cursor: pointer;
  transition: all 0.2s;
}

.action-icon-btn:hover {
  background: #333;
}

.action-icon-btn.add-child:hover {
  color: #4CAF50;
}

.action-icon-btn.edit:hover {
  color: #2196F3;
}

.action-icon-btn.delete:hover {
  color: #f44336;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #666;
}

/* 对话框样式 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: #1a1a1a;
  border-radius: 12px;
  padding: 24px;
  width: 90%;
  max-width: 400px;
}

.dialog h3 {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  margin: 0 0 20px 0;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 14px;
  color: #999;
  margin-bottom: 8px;
}

.form-group input,
.parent-select {
  width: 100%;
  height: 44px;
  padding: 0 12px;
  border: 1px solid #333;
  border-radius: 8px;
  background: #252525;
  color: #fff;
  font-size: 14px;
  box-sizing: border-box;
}

.form-group input:focus,
.parent-select:focus {
  outline: none;
  border-color: #2196F3;
}

/* 智能建议下拉框 */
.suggestion-wrapper {
  position: relative;
}

.suggestions-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #2a2a2a;
  border: 1px solid #444;
  border-top: none;
  border-radius: 0 0 8px 8px;
  max-height: 200px;
  overflow-y: auto;
  z-index: 100;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.suggestion-item {
  padding: 10px 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #333;
}

.suggestion-item:last-child {
  border-bottom: none;
}

.suggestion-item:hover {
  background: #3a3a3a;
}

.suggestion-path {
  color: #fff;
  font-size: 14px;
}

.suggestion-category {
  color: #888;
  font-size: 12px;
  background: #444;
  padding: 2px 8px;
  border-radius: 4px;
}

.suggestion-empty {
  padding: 10px 12px;
  color: #888;
  font-size: 13px;
  text-align: center;
}

.error-text {
  color: #f44336;
  font-size: 13px;
  margin: -8px 0 16px 0;
}

.warning-text {
  color: #ff9800;
  font-size: 13px;
  margin: 12px 0;
}

.dialog-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 20px;
}

.btn-secondary {
  padding: 10px 20px;
  background: transparent;
  border: 1px solid #444;
  border-radius: 6px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-secondary:hover {
  background: #333;
}

.btn-primary {
  padding: 10px 20px;
  background: #2196F3;
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: #1976D2;
}

.btn-danger {
  padding: 10px 20px;
  background: #f44336;
  border: none;
  border-radius: 6px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-danger:hover {
  background: #d32f2f;
}

@media (max-width: 768px) {
  .tags-page {
    padding: 16px;
  }

  .page-title {
    font-size: 22px;
  }

  .tag-actions {
    opacity: 1;
  }
}
</style>
