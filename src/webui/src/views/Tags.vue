<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useVideoStore } from '../stores/videoStore'
import { useUserStore } from '../stores/userStore'
import { tagApi } from '../api'
import type { Tag } from '../types'

const videoStore = useVideoStore()
const userStore = useUserStore()

// 管理员友好：是否允许编辑（仅管理员）
const isAdmin = computed(() => userStore.isAdmin)

const loading = computed(() => videoStore.loading)

// 标签列表 - 使用融合模式获取用户可见的所有标签
const allTagsList = ref<Tag[]>([])
const searchQuery = ref('')
const expandedTags = ref<Set<number>>(new Set())

// 获取标签列表 - 使用融合模式，自动合并用户有权限的视频库中的相同标签
const fetchAllTags = async () => {
  try {
    // 使用 merge=true 获取融合后的标签列表，用户能看到所有有权限的视频库的标签
    const response = await tagApi.getTags({ tree: false, merge: true }) as any
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


// 查看标签下的视频 - 跳转到首页并筛选该标签（统一使用数字 tag id 作为 URL 参数，
// 与首页标签筛选保持一致，确保从标签页点击眼睛图标筛选能真正生效）
import { useRouter } from 'vue-router'

const router = useRouter()

const viewTagVideos = (tag: Tag) => {
  router.push({ path: '/', query: { tag: String(tag.id) } })
}

// ============ 管理员：新建 / 编辑 / 删除 标签 ============
const showDialog = ref(false)
const dialogMode = ref<'create' | 'edit'>('create')
const dialogTag = ref<Tag | null>(null)
const dialogName = ref('')
const dialogCategory = ref('')
const dialogParentId = ref<number | null>(null)
const dialogError = ref('')

// 轻量 toast
const toastMessage = ref('')
const toastTimer = ref<number | null>(null)
const showToast = (message: string) => {
  toastMessage.value = message
  if (toastTimer.value) window.clearTimeout(toastTimer.value)
  toastTimer.value = window.setTimeout(() => { toastMessage.value = '' }, 2500)
}

// 打开新建标签对话框
const openCreateDialog = () => {
  dialogMode.value = 'create'
  dialogTag.value = null
  dialogName.value = ''
  dialogCategory.value = ''
  dialogParentId.value = null
  dialogError.value = ''
  showDialog.value = true
}

// 打开编辑标签对话框
const openEditDialog = (tag: Tag) => {
  dialogMode.value = 'edit'
  dialogTag.value = tag
  dialogName.value = tag.name
  dialogCategory.value = tag.category || ''
  dialogParentId.value = tag.parent_id || null
  dialogError.value = ''
  showDialog.value = true
}

// 提交新建 / 编辑
const submitDialog = async () => {
  const name = dialogName.value.trim()
  if (!name) {
    dialogError.value = '标签名不能为空'
    return
  }
  try {
    if (dialogMode.value === 'create') {
      await tagApi.createTag(name, dialogCategory.value.trim() || '类型', dialogParentId.value || undefined)
      showToast('标签已创建')
    } else if (dialogTag.value) {
      await tagApi.updateTag(dialogTag.value.id, {
        name,
        category: dialogCategory.value.trim() || '类型',
        parent_id: dialogParentId.value || null
      })
      showToast('标签已更新')
    }
    showDialog.value = false
    await fetchAllTags()
  } catch (e: any) {
    dialogError.value = e?.response?.data?.message || '操作失败'
  }
}

// 删除标签（二次确认）
const pendingDelete = ref<Tag | null>(null)
const confirmDeleteTag = (tag: Tag) => {
  pendingDelete.value = tag
}
const cancelDelete = () => { pendingDelete.value = null }
const doDeleteTag = async () => {
  if (!pendingDelete.value) return
  try {
    await tagApi.deleteTag(pendingDelete.value.id)
    showToast('标签已删除')
    pendingDelete.value = null
    await fetchAllTags()
  } catch (e: any) {
    showToast(e?.response?.data?.message || '删除失败')
    pendingDelete.value = null
  }
}
</script>

<template>
  <div class="tags-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">标签</h1>
        <p class="page-desc">点击标签可查看对应的内容（视频或漫画共用同一套标签）</p>
      </div>
      <button v-if="isAdmin" class="create-btn" @click="openCreateDialog">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="12" y1="5" x2="12" y2="19"/>
          <line x1="5" y1="12" x2="19" y2="12"/>
        </svg>
        新建标签
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
              <span class="tag-count">{{ countAllVideos(item.tag) }} 个内容</span>
              <span v-if="getChildren(item.tag.id).length > 0" class="tag-children-count">
                {{ getChildren(item.tag.id).length }} 个子标签
              </span>
            </div>
          </div>
          
          <!-- 操作按钮 -->
          <div class="tag-actions" :class="{ admin: isAdmin }">
            <button
              class="action-icon-btn view"
              @click="viewTagVideos(item.tag)"
              title="查看视频"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 4.5C7 4.5 2.73 7.61 1 12c1.73 4.39 6 7.5 11 7.5s9.27-3.11 11-7.5c-1.73-4.39-6-7.5-11-7.5zM12 17c-2.76 0-5-2.24-5-5s2.24-5 5-5 5 2.24 5 5-2.24 5-5 5zm0-8c-1.66 0-3 1.34-3 3s1.34 3 3 3 3-1.34 3-3-1.34-3-3-3z"/>
              </svg>
            </button>
            <template v-if="isAdmin">
              <button
                class="action-icon-btn edit"
                @click="openEditDialog(item.tag)"
                title="编辑标签"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
                </svg>
              </button>
              <button
                class="action-icon-btn delete"
                @click="confirmDeleteTag(item.tag)"
                title="删除标签"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline points="3 6 5 6 21 6"/>
                  <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  <line x1="10" y1="11" x2="10" y2="17"/>
                  <line x1="14" y1="11" x2="14" y2="17"/>
                </svg>
              </button>
            </template>
          </div>
        </div>
      </template>

      <!-- 空状态 -->
      <div v-if="displayTags.length === 0" class="empty-state">
        <p v-if="searchQuery">没有找到匹配的标签</p>
        <p v-else>暂无标签，在视频或漫画中添加标签后会自动显示</p>
      </div>
    </div>

  </div>

  <!-- 新建 / 编辑标签对话框 -->
  <div v-if="showDialog" class="dialog-overlay" @click.self="showDialog = false">
    <div class="dialog">
      <h3>{{ dialogMode === 'create' ? '新建标签' : '编辑标签' }}</h3>
      <div class="form-group">
        <label>标签名称</label>
        <input v-model="dialogName" type="text" placeholder="如：科幻" maxlength="20" @keydown.enter="submitDialog" />
      </div>
      <div class="form-group">
        <label>分类（可选）</label>
        <input v-model="dialogCategory" type="text" placeholder="如：类型" maxlength="20" />
      </div>
      <div class="form-group">
        <label>父标签（可选）</label>
        <select v-model="dialogParentId" class="parent-select">
          <option :value="null">顶级标签</option>
          <option
            v-for="t in allTagsList.filter(t => t.id !== dialogTag?.id)"
            :key="t.id"
            :value="t.id"
          >{{ t.path || t.name }}</option>
        </select>
      </div>
      <p v-if="dialogError" class="error-text">{{ dialogError }}</p>
      <div class="dialog-actions">
        <button class="btn-secondary" @click="showDialog = false">取消</button>
        <button class="btn-primary" @click="submitDialog">
          {{ dialogMode === 'create' ? '创建' : '保存' }}
        </button>
      </div>
    </div>
  </div>

  <!-- 删除确认 -->
  <div v-if="pendingDelete" class="dialog-overlay" @click.self="cancelDelete">
    <div class="dialog">
      <h3>删除标签</h3>
      <p class="warning-text">
        确定要删除标签「{{ pendingDelete.name }}」吗？<br/>
        该标签及其下所有视频的关联将被移除（子标签会提升为顶级）。
      </p>
      <div class="dialog-actions">
        <button class="btn-secondary" @click="cancelDelete">取消</button>
        <button class="btn-danger" @click="doDeleteTag">删除</button>
      </div>
    </div>
  </div>

  <!-- Toast -->
  <div v-if="toastMessage" class="toast">{{ toastMessage }}</div>
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

/* 管理员视图下操作按钮常驻显示，方便快速操作 */
.tag-actions.admin {
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

/* Toast 提示 */
.toast {
  position: fixed;
  bottom: 32px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(33, 33, 33, 0.95);
  color: #fff;
  padding: 12px 24px;
  border-radius: 8px;
  font-size: 14px;
  z-index: 2000;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.4);
  animation: toastSlideIn 0.25s ease;
}

@keyframes toastSlideIn {
  from { opacity: 0; transform: translate(-50%, 12px); }
  to { opacity: 1; transform: translate(-50%, 0); }
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
