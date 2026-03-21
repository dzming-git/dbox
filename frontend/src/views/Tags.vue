<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useVideoStore } from '../stores/videoStore'
import type { Tag } from '../types'

const videoStore = useVideoStore()

const loading = computed(() => videoStore.loading)
const tags = computed(() => videoStore.tags)
const searchQuery = ref('')

// 筛选后的标签
const filteredTags = computed(() => {
  if (!searchQuery.value) return tags.value
  const query = searchQuery.value.toLowerCase()
  return tags.value.filter(tag => 
    tag.name.toLowerCase().includes(query) ||
    (tag.category && tag.category.toLowerCase().includes(query))
  )
})

// 按分类分组的标签
const groupedTags = computed(() => {
  const groups: Record<string, Tag[]> = {}
  filteredTags.value.forEach(tag => {
    const category = tag.category || '未分类'
    if (!groups[category]) {
      groups[category] = []
    }
    groups[category].push(tag)
  })
  return groups
})

onMounted(async () => {
  await videoStore.fetchTags()
})

// 创建标签
const showCreateDialog = ref(false)
const newTagName = ref('')
const newTagCategory = ref('')
const createError = ref('')

const openCreateDialog = () => {
  newTagName.value = ''
  newTagCategory.value = ''
  createError.value = ''
  showCreateDialog.value = true
}

const handleCreateTag = async () => {
  if (!newTagName.value.trim()) {
    createError.value = '标签名称不能为空'
    return
  }
  
  try {
    await videoStore.createTag(newTagName.value.trim(), newTagCategory.value.trim() || undefined)
    showCreateDialog.value = false
  } catch (e) {
    createError.value = '创建标签失败，可能标签已存在'
  }
}

// 编辑标签
const editingTag = ref<Tag | null>(null)
const editTagName = ref('')
const editTagCategory = ref('')
const editError = ref('')

const openEditDialog = (tag: Tag) => {
  editingTag.value = tag
  editTagName.value = tag.name
  editTagCategory.value = tag.category || ''
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
      category: editTagCategory.value.trim() || undefined
    })
    editingTag.value = null
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
  } catch (e) {
    alert('删除标签失败')
  }
}

// 按视频数排序
const sortByCount = () => {
  const sorted = [...tags.value].sort((a, b) => b.video_count - a.video_count)
  videoStore.tags = sorted
}
</script>

<template>
  <div class="tags-page">
    <div class="page-header">
      <h1 class="page-title">标签管理</h1>
      <button class="create-btn" @click="openCreateDialog" data-testid="create-tag-button">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
          <path d="M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"/>
        </svg>
        创建标签
      </button>
    </div>

    <!-- 搜索和工具栏 -->
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
          data-testid="tag-search-input"
        />
      </div>
      <button class="sort-btn" @click="sortByCount">
        按视频数排序
      </button>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-container">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 标签列表 -->
    <div v-else class="tags-content">
      <!-- 按分类显示 -->
      <div v-for="(categoryTags, category) in groupedTags" :key="category" class="category-section">
        <h2 class="category-title">{{ category }} ({{ categoryTags.length }})</h2>
        <div class="tags-grid">
          <div 
            v-for="tag in categoryTags" 
            :key="tag.id"
            class="tag-card"
            data-testid="tag-item"
          >
            <div class="tag-info">
              <span class="tag-name" data-testid="tag-name">{{ tag.name }}</span>
              <span class="tag-count" data-testid="tag-video-count">{{ tag.video_count }} 个视频</span>
            </div>
            <div class="tag-actions">
              <button 
                class="action-icon-btn edit" 
                @click="openEditDialog(tag)"
                data-testid="edit-button"
                title="编辑"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zM20.71 7.04c.39-.39.39-1.02 0-1.41l-2.34-2.34c-.39-.39-1.02-.39-1.41 0l-1.83 1.83 3.75 3.75 1.83-1.83z"/>
                </svg>
              </button>
              <button 
                class="action-icon-btn delete" 
                @click="confirmDelete(tag)"
                data-testid="delete-button"
                title="删除"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="filteredTags.length === 0" class="empty-state">
        <p v-if="searchQuery">没有找到匹配的标签</p>
        <p v-else>暂无标签，点击上方按钮创建</p>
      </div>
    </div>

    <!-- 创建标签对话框 -->
    <div v-if="showCreateDialog" class="dialog-overlay" data-testid="tag-create-dialog">
      <div class="dialog">
        <h3>创建新标签</h3>
        <div class="form-group">
          <label>标签名称</label>
          <input 
            v-model="newTagName" 
            type="text" 
            placeholder="输入标签名称"
            data-testid="tag-name-input"
            @keyup.enter="handleCreateTag"
          />
        </div>
        <div class="form-group">
          <label>分类（可选）</label>
          <input 
            v-model="newTagCategory" 
            type="text" 
            placeholder="输入分类名称"
            data-testid="tag-category-select"
            @keyup.enter="handleCreateTag"
          />
        </div>
        <p v-if="createError" class="error-text">{{ createError }}</p>
        <div class="dialog-actions">
          <button class="btn-secondary" @click="showCreateDialog = false">取消</button>
          <button class="btn-primary" @click="handleCreateTag" data-testid="create-tag-confirm-button">创建</button>
        </div>
      </div>
    </div>

    <!-- 编辑标签对话框 -->
    <div v-if="editingTag" class="dialog-overlay" data-testid="tag-edit-dialog">
      <div class="dialog">
        <h3>编辑标签</h3>
        <div class="form-group">
          <label>标签名称</label>
          <input 
            v-model="editTagName" 
            type="text" 
            placeholder="输入标签名称"
            data-testid="tag-name-input"
            @keyup.enter="handleUpdateTag"
          />
        </div>
        <div class="form-group">
          <label>分类（可选）</label>
          <input 
            v-model="editTagCategory" 
            type="text" 
            placeholder="输入分类名称"
            data-testid="tag-category-select"
            @keyup.enter="handleUpdateTag"
          />
        </div>
        <p v-if="editError" class="error-text">{{ editError }}</p>
        <div class="dialog-actions">
          <button class="btn-secondary" @click="editingTag = null">取消</button>
          <button class="btn-primary" @click="handleUpdateTag" data-testid="save-tag-button">保存</button>
        </div>
      </div>
    </div>

    <!-- 删除确认对话框 -->
    <div v-if="deletingTag" class="dialog-overlay" data-testid="delete-confirm-dialog">
      <div class="dialog">
        <h3>确认删除</h3>
        <p>确定要删除标签 "{{ deletingTag.name }}" 吗？</p>
        <p v-if="deletingTag.video_count > 0" class="warning-text">
          该标签关联了 {{ deletingTag.video_count }} 个视频，删除后将移除这些关联。
        </p>
        <div class="dialog-actions">
          <button class="btn-secondary" @click="deletingTag = null">取消</button>
          <button class="btn-danger" @click="handleDeleteTag" data-testid="confirm-delete-button">删除</button>
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

.sort-btn {
  padding: 10px 20px;
  background: #333;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.sort-btn:hover {
  background: #444;
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

.category-section {
  margin-bottom: 32px;
}

.category-title {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  margin: 0 0 16px 0;
  padding-bottom: 8px;
  border-bottom: 1px solid #333;
}

.tags-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 12px;
}

.tag-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: #1a1a1a;
  border-radius: 8px;
  transition: background 0.2s;
}

.tag-card:hover {
  background: #252525;
}

.tag-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tag-name {
  font-size: 15px;
  font-weight: 500;
  color: #fff;
}

.tag-count {
  font-size: 13px;
  color: #999;
}

.tag-actions {
  display: flex;
  gap: 8px;
  opacity: 0;
  transition: opacity 0.2s;
}

.tag-card:hover .tag-actions {
  opacity: 1;
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

.form-group input {
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

.form-group input:focus {
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

  .tags-grid {
    grid-template-columns: 1fr;
  }

  .tag-actions {
    opacity: 1;
  }
}
</style>
