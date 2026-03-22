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

// 创建标签
const showCreateDialog = ref(false)
const newTagName = ref('')
const newTagCategory = ref('')
const newTagParentId = ref<number | null>(null)
const createError = ref('')

const openCreateDialog = (parentId: number | null = null) => {
  newTagName.value = ''
  newTagCategory.value = ''
  newTagParentId.value = parentId
  createError.value = ''
  showCreateDialog.value = true
}

const handleCreateTag = async () => {
  if (!newTagName.value.trim()) {
    createError.value = '标签名称不能为空'
    return
  }
  
  try {
    await videoStore.createTag(
      newTagName.value.trim(), 
      newTagCategory.value.trim() || undefined,
      newTagParentId.value || undefined
    )
    showCreateDialog.value = false
    await fetchAllTags()
  } catch (e) {
    createError.value = '创建标签失败，可能标签已存在'
  }
}

// 编辑标签
const editingTag = ref<Tag | null>(null)
const editTagName = ref('')
const editTagCategory = ref('')
const editTagParentId = ref<number | null>(null)
const editError = ref('')

const openEditDialog = (tag: Tag) => {
  editingTag.value = tag
  editTagName.value = tag.name
  editTagCategory.value = tag.category || ''
  editTagParentId.value = tag.parent_id || null
  editError.value = ''
}

const handleUpdateTag = async () => {
  if (!editingTag.value) return
  if (!editTagName.value.trim()) {
    editError.value = '标签名称不能为空'
    return
  }
  
  try {
    await videoStore.updateTag(editingTag.value.id, {
      name: editTagName.value.trim(),
      category: editTagCategory.value.trim() || undefined,
      parent_id: editTagParentId.value
    })
    editingTag.value = null
    await fetchAllTags()
  } catch (e) {
    editError.value = '更新标签失败'
  }
}

// 删除标签
const deletingTag = ref<Tag | null>(null)

const confirmDelete = (tag: Tag) => {
  deletingTag.value = tag
}

const handleDeleteTag = async () => {
  if (!deletingTag.value) return
  
  try {
    await videoStore.deleteTag(deletingTag.value.id)
    deletingTag.value = null
    await fetchAllTags()
  } catch (e) {
    alert('删除标签失败')
  }
}
</script>

<template>
  <div class="tags-page">
    <div class="page-header">
      <h1 class="page-title">标签管理</h1>
      <button class="create-btn" @click="openCreateDialog(null)">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
        </svg>
        创建标签
      </button>
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
          
          <!-- 操作按钮 -->
          <div class="tag-actions">
            <button 
              class="action-icon-btn add-child" 
              @click="openCreateDialog(item.tag.id)"
              title="添加子标签"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
              </svg>
            </button>
            <button 
              class="action-icon-btn edit" 
              @click="openEditDialog(item.tag)"
              title="编辑"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
              </svg>
            </button>
            <button 
              class="action-icon-btn delete" 
              @click="confirmDelete(item.tag)"
              title="删除"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
              </svg>
            </button>
          </div>
        </div>
      </template>

      <!-- 空状态 -->
      <div v-if="displayTags.length === 0" class="empty-state">
        <p v-if="searchQuery">没有找到匹配的标签</p>
        <p v-else>暂无标签，点击上方按钮创建</p>
      </div>
    </div>

    <!-- 创建标签对话框 -->
    <div v-if="showCreateDialog" class="dialog-overlay">
      <div class="dialog">
        <h3>{{ newTagParentId ? '创建子标签' : '创建新标签' }}</h3>
        <div class="form-group">
          <label>标签名称</label>
          <input 
            v-model="newTagName" 
            type="text" 
            placeholder="输入标签名称"
            @keyup.enter="handleCreateTag"
          />
        </div>
        <div class="form-group">
          <label>分类（可选）</label>
          <input 
            v-model="newTagCategory" 
            type="text" 
            placeholder="输入分类名称"
            @keyup.enter="handleCreateTag"
          />
        </div>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="dialog-actions">
          <button class="btn-secondary" @click="showCreateDialog = false">取消</button>
          <button class="btn-primary" @click="handleCreateTag">创建</button>
        </div>
      </div>
    </div>

    <!-- 编辑标签对话框 -->
    <div v-if="editingTag" class="dialog-overlay">
      <div class="dialog">
        <h3>编辑标签</h3>
        <div class="form-group">
          <label>标签名称</label>
          <input 
            v-model="editTagName" 
            type="text" 
            placeholder="输入标签名称"
            @keyup.enter="handleUpdateTag"
          />
        </div>
        <div class="form-group">
          <label>分类（可选）</label>
          <input 
            v-model="editTagCategory" 
            type="text" 
            placeholder="输入分类名称"
            @keyup.enter="handleUpdateTag"
          />
        </div>
        <div class="form-group">
          <label>父标签</label>
          <select v-model="editTagParentId" class="parent-select">
            <option :value="null">顶级标签</option>
            <option 
              v-for="tag in allTagsList.filter(t => t.id !== editingTag?.id)" 
              :key="tag.id" 
              :value="tag.id"
            >
              {{ tag.name }}
            </option>
          </select>
        </div>
        <p v-if="editError" class="error-text">{{ editError }}</p>
        <div class="dialog-actions">
          <button class="btn-secondary" @click="editingTag = null">取消</button>
          <button class="btn-primary" @click="handleUpdateTag">保存</button>
        </div>
      </div>
    </div>

    <!-- 删除确认对话框 -->
    <div v-if="deletingTag" class="dialog-overlay">
      <div class="dialog">
        <h3>确认删除</h3>
        <p>确定要删除标签 "{{ deletingTag.name }}" 吗？</p>
        <p v-if="getChildren(deletingTag.id).length > 0" class="warning-text">
          该标签有 {{ getChildren(deletingTag.id).length }} 个子标签，删除后子标签将变为顶级标签。
        </p>
        <p v-if="(deletingTag.video_count || 0) > 0" class="warning-text">
          该标签关联了 {{ deletingTag.video_count }} 个视频，删除后将移除这些关联。
        </p>
        <div class="dialog-actions">
          <button class="btn-secondary" @click="deletingTag = null">取消</button>
          <button class="btn-danger" @click="handleDeleteTag">删除</button>
        </div>
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
