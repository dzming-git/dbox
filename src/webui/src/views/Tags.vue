<script setup lang="ts">
defineOptions({ name: 'Tags' })
import { ref, onMounted, computed, onActivated, onDeactivated } from 'vue'
import { useUserStore } from '../stores/userStore'
import { useTagStore } from '../stores/tagStore'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import { tagApi } from '../api/tag'
import { libraryApi } from '../api/library'
import type { Tag } from '../types'

const userStore = useUserStore()
const tagStore = useTagStore()

// 管理员友好：是否允许编辑（仅管理员）
const isAdmin = computed(() => userStore.isAdmin)

const loading = computed(() => tagStore.loading)

// 标签列表 - 使用融合模式获取用户可见的所有标签
const allTagsList = ref<Tag[]>([])
const searchQuery = ref('')
const expandedTags = ref<Set<number>>(new Set())

// 获取标签列表 - 使用融合模式，自动合并用户有权限的资源库中的相同标签
const fetchAllTags = async () => {
  try {
    // 使用 merge=true 获取融合后的标签列表，用户能看到所有有权限的资源库的标签
    await tagStore.fetchTags({ tree: false, merge: true })
    allTagsList.value = tagStore.tags as Tag[]
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
  if (isAdmin) await loadLibraries()
})

// 顶部下拉刷新：重新拉取标签
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(fetchAllTags)
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())

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
const dialogQualifiers = ref('')  // 补充项（换行/逗号分隔的原始文本）
const dialogCategory = ref('')
const dialogParentId = ref<number | null>(null)
const dialogLibraryId = ref<number | null>(null)  // 标签集（资源库）归属
const dialogError = ref('')

// 资源库（标签集）列表
const libraries = ref<{ id: number, name: string }[]>([])
const loadLibraries = async () => {
  try {
    const res: any = await libraryApi.getLibraries()
    libraries.value = Array.isArray(res) ? res : (res.data || [])
  } catch (e) {
    libraries.value = []
  }
}

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
  dialogQualifiers.value = ''
  dialogCategory.value = ''
  dialogParentId.value = null
  dialogLibraryId.value = null
  dialogError.value = ''
  showDialog.value = true
}

// 打开编辑标签对话框
const openEditDialog = (tag: Tag) => {
  dialogMode.value = 'edit'
  dialogTag.value = tag
      dialogName.value = tag.name
  dialogQualifiers.value = (tag.qualifiers || []).join('\n')
  dialogCategory.value = tag.category || ''
  dialogParentId.value = tag.parent_id || null
  dialogLibraryId.value = tag.library_id ?? null
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
  // 层级限制：父级深度 + 1 不能超过最大层级
  let parentDepth = 0
  if (dialogParentId.value) {
    const parent = allTagsList.value.find(t => t.id === dialogParentId.value)
    if (parent) parentDepth = tagDepth(parent)
  }
  if (parentDepth + 1 > MAX_TAG_DEPTH) {
    dialogError.value = `超过最大层级限制（${MAX_TAG_DEPTH} 层）`
    return
  }
  try {
    if (dialogMode.value === 'create') {
      await tagApi.createTag(
        name,
        dialogCategory.value.trim() || '类型',
        dialogParentId.value || undefined,
        dialogQualifiers.value.trim() || undefined,
        dialogLibraryId.value
      )
      showToast('标签已创建')
    } else if (dialogTag.value) {
      await tagApi.updateTag(dialogTag.value.id, {
        name,
        qualifiers: dialogQualifiers.value.trim() || null,
        category: dialogCategory.value.trim() || '类型',
        parent_id: dialogParentId.value || null,
        library_id: dialogLibraryId.value
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

// ============ 层级限制 ============
const MAX_TAG_DEPTH = 8
// 计算某标签当前深度（顶级为 1）
const tagDepth = (tag: Tag): number => {
  let d = 1
  let cur: Tag | undefined = tag
  const byId = new Map(allTagsList.value.map(t => [t.id, t]))
  while (cur && cur.parent_id) {
    const p = byId.get(cur.parent_id)
    if (!p) break
    d++
    cur = p
  }
  return d
}

// ============ 批量操作 ============
const batchMode = ref(false)
const selectedIds = ref<number[]>([])
const allTagIds = computed(() => allTagsList.value.map(t => t.id))
const selectedCount = computed(() => selectedIds.value.length)

const toggleBatchMode = () => {
  batchMode.value = !batchMode.value
  if (!batchMode.value) selectedIds.value = []
}
const isSelected = (id: number) => selectedIds.value.includes(id)
const toggleSelect = (id: number) => {
  if (isSelected(id)) selectedIds.value = selectedIds.value.filter(x => x !== id)
  else selectedIds.value = [...selectedIds.value, id]
}
const toggleSelectAll = () => {
  if (selectedIds.value.length === allTagIds.value.length) selectedIds.value = []
  else selectedIds.value = [...allTagIds.value]
}

// 批量移动
const showBatchMoveDialog = ref(false)
const batchMoveParentId = ref<number | null>(null)
const batchMoveError = ref('')

const openBatchMove = () => {
  if (selectedCount.value === 0) return
  batchMoveParentId.value = null
  batchMoveError.value = ''
  showBatchMoveDialog.value = true
}
const confirmBatchMove = async () => {
  try {
    // 校验目标不能是选中项的子孙（避免环）
    if (batchMoveParentId.value) {
      const parent = allTagsList.value.find(t => t.id === batchMoveParentId.value)
      if (parent && tagDepth(parent) + 1 > MAX_TAG_DEPTH) {
        batchMoveError.value = `超过最大层级限制（${MAX_TAG_DEPTH} 层）`
        return
      }
    }
    await tagApi.batchMoveTags(selectedIds.value, batchMoveParentId.value)
    showToast(`已移动 ${selectedCount.value} 个标签`)
    showBatchMoveDialog.value = false
    selectedIds.value = []
    await fetchAllTags()
  } catch (e: any) {
    batchMoveError.value = e?.response?.data?.message || '批量移动失败'
  }
}

// 批量删除
const batchDelete = async () => {
  if (selectedCount.value === 0) return
  if (!window.confirm(`确认删除选中的 ${selectedCount.value} 个标签？子标签将提升为顶级。`)) return
  try {
    await tagApi.batchDeleteTags(selectedIds.value)
    showToast(`已删除 ${selectedCount.value} 个标签`)
    selectedIds.value = []
    await fetchAllTags()
  } catch (e: any) {
    showToast(e?.response?.data?.message || '批量删除失败')
  }
}

// ============ 标签合并 ============
const showMergeDialog = ref(false)
const mergeTargetId = ref<number | null>(null)
const mergeError = ref('')

const openMerge = () => {
  if (selectedCount.value < 1) return
  mergeTargetId.value = null
  mergeError.value = ''
  showMergeDialog.value = true
}
const confirmMerge = async () => {
  if (!mergeTargetId.value) {
    mergeError.value = '请选择目标标签'
    return
  }
  if (selectedIds.value.includes(mergeTargetId.value)) {
    mergeError.value = '目标标签不能是已选源标签之一'
    return
  }
  try {
    const res = await tagApi.mergeTags(selectedIds.value, mergeTargetId.value)
    showToast(`已合并 ${selectedCount.value} 个标签`)
    showMergeDialog.value = false
    selectedIds.value = []
    await fetchAllTags()
  } catch (e: any) {
    mergeError.value = e?.response?.data?.message || '合并失败'
  }
}

// 提交时校验层级限制（已合并进 submitDialog，此处无需额外函数）
</script>

<template>
  <div class="tags-page">
    <div class="page-header">
      <div>
        <h1 class="page-title">标签</h1>
        <p class="page-desc">点击标签可查看对应的内容（视频或图集共用同一套标签）</p>
      </div>
      <div class="header-actions" v-if="isAdmin">
        <button class="batch-toggle-btn" :class="{ active: batchMode }" @click="toggleBatchMode">
          {{ batchMode ? '退出批量' : '批量管理' }}
        </button>
        <button class="create-btn" @click="openCreateDialog">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <line x1="12" y1="5" x2="12" y2="19"/>
            <line x1="5" y1="12" x2="19" y2="12"/>
          </svg>
          新建标签
        </button>
      </div>
    </div>

    <!-- 批量操作栏 -->
    <div v-if="batchMode && isAdmin" class="batch-bar">
      <label class="batch-select-all">
        <input type="checkbox" :checked="selectedIds.length === allTagIds.length" @change="toggleSelectAll" />
        <span>全选（{{ selectedCount }}/{{ allTagIds.length }}）</span>
      </label>
      <div class="batch-actions">
        <button class="batch-btn move" @click="openBatchMove" :disabled="selectedCount === 0">批量移动父级</button>
        <button class="batch-btn merge" @click="openMerge" :disabled="selectedCount === 0">合并到</button>
        <button class="batch-btn danger" @click="batchDelete" :disabled="selectedCount === 0">批量删除</button>
      </div>
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
          <!-- 批量选择复选框 -->
          <label v-if="batchMode && isAdmin" class="batch-check">
            <input
              type="checkbox"
              :checked="isSelected(item.tag.id)"
              @change="toggleSelect(item.tag.id)"
            />
          </label>

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
              <span v-if="item.tag.qualifiers && item.tag.qualifiers.length" class="tag-qualifiers">
                <span v-for="q in item.tag.qualifiers" :key="q" class="q-chip">{{ q }}</span>
              </span>
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
        <p v-else>暂无标签，在视频或图集中添加标签后会自动显示</p>
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
        <label>补充项（可选，每行或逗号分隔，如：白 / 长毛 / 橘；视频打此标签时从中勾选）</label>
        <textarea v-model="dialogQualifiers" rows="2" placeholder="留空则无补充项"></textarea>
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
      <div class="form-group" v-if="isAdmin">
        <label>标签集（资源库，可选）</label>
        <select v-model="dialogLibraryId" class="parent-select">
          <option :value="null">全局标签（所有资源库可用）</option>
          <option
            v-for="lib in libraries"
            :key="lib.id"
            :value="lib.id"
          >{{ lib.name }}</option>
        </select>
        <p class="hint-text">归属到指定资源库后，仅该资源库下的视频可使用此标签；留空则为全局标签。</p>
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

  <!-- 批量移动父级对话框 -->
  <div v-if="showBatchMoveDialog" class="dialog-overlay" @click.self="showBatchMoveDialog = false">
    <div class="dialog">
      <h3>批量移动父级</h3>
      <p class="warning-text">将选中的 {{ selectedCount }} 个标签移动到以下父级：</p>
      <div class="form-group">
        <label>目标父标签</label>
        <select v-model="batchMoveParentId" class="parent-select">
          <option :value="null">顶级标签</option>
          <option
            v-for="t in allTagsList.filter(t => !selectedIds.includes(t.id))"
            :key="t.id"
            :value="t.id"
          >{{ t.path || t.name }}</option>
        </select>
      </div>
      <p v-if="batchMoveError" class="error-text">{{ batchMoveError }}</p>
      <div class="dialog-actions">
        <button class="btn-secondary" @click="showBatchMoveDialog = false">取消</button>
        <button class="btn-primary" @click="confirmBatchMove">确定移动</button>
      </div>
    </div>
  </div>

  <!-- 合并对话框 -->
  <div v-if="showMergeDialog" class="dialog-overlay" @click.self="showMergeDialog = false">
    <div class="dialog">
      <h3>合并标签</h3>
      <p class="warning-text">
        将选中的 {{ selectedCount }} 个标签合并到目标标签，源标签的视频关联将转移并删除源标签。
      </p>
      <div class="form-group">
        <label>目标标签</label>
        <select v-model="mergeTargetId" class="parent-select">
          <option :value="null">请选择目标标签</option>
          <option
            v-for="t in allTagsList.filter(t => !selectedIds.includes(t.id))"
            :key="t.id"
            :value="t.id"
          >{{ t.path || t.name }}</option>
        </select>
      </div>
      <p v-if="mergeError" class="error-text">{{ mergeError }}</p>
      <div class="dialog-actions">
        <button class="btn-secondary" @click="showMergeDialog = false">取消</button>
        <button class="btn-primary" @click="confirmMerge">确定合并</button>
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
  color: var(--text-primary);
  margin: 0;
}

.page-desc {
  font-size: 14px;
  color: var(--text-secondary);
  margin: 0;
}

.create-btn {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 24px;
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: var(--text-on-accent);
  font-size: 15px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.create-btn:hover {
  background: var(--accent-active);
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
  color: var(--text-tertiary);
}

.search-input {
  width: 100%;
  height: 44px;
  padding: 0 16px 0 44px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--bg-surface);
  color: var(--text-primary);
  font-size: 14px;
}

.search-input:focus {
  outline: none;
  border-color: var(--accent);
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
  border: 3px solid var(--border-default);
  border-top-color: var(--accent);
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
  background: var(--bg-surface);
  border-radius: 8px;
  transition: all 0.2s;
}

.tag-row:hover {
  background: var(--bg-surface-hover);
}

.tag-row:hover .tag-actions {
  opacity: 1;
}

/* 层级样式 */
.tag-row.level-0 {
  background: var(--info-soft);
}

.tag-row.level-1 {
  background: var(--info-soft);
}

.tag-row.level-2 {
  background: var(--info-soft);
}

.tag-row.level-3 {
  background: var(--danger-soft);
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
  background: var(--border-strong);
}

.expand-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: transparent;
  border: none;
  color: var(--text-tertiary);
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
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 200px;
}

.level-badge {
  font-size: 10px;
  color: var(--text-secondary);
  background: var(--bg-surface-2);
  padding: 2px 6px;
  border-radius: 3px;
  flex-shrink: 0;
}

.tag-category {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-surface-2);
  padding: 2px 8px;
  border-radius: 4px;
  flex-shrink: 0;
  white-space: nowrap;
}

.tag-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: var(--text-tertiary);
}

.tag-children-count {
  color: var(--accent);
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
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.2s;
}

.action-icon-btn:hover {
  background: var(--bg-surface-2);
}

.action-icon-btn.add-child:hover {
  color: #4CAF50;
}

.action-icon-btn.edit:hover {
  color: var(--accent);
}

.action-icon-btn.delete:hover {
  color: #f44336;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: var(--text-tertiary);
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
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 24px;
  width: 90%;
  max-width: 400px;
}

.dialog h3 {
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 20px 0;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  font-size: 14px;
  color: var(--text-tertiary);
  margin-bottom: 8px;
}

.form-group input,
.parent-select {
  width: 100%;
  height: 44px;
  padding: 0 12px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  font-size: 14px;
  box-sizing: border-box;
}

.form-group input:focus,
.parent-select:focus {
  outline: none;
  border-color: var(--accent);
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
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-strong);
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
  border-bottom: 1px solid var(--border-default);
}

.suggestion-item:last-child {
  border-bottom: none;
}

.suggestion-item:hover {
  background: var(--bg-surface-hover);
}

.suggestion-path {
  color: var(--text-primary);
  font-size: 14px;
}

.suggestion-category {
  color: var(--text-secondary);
  font-size: 12px;
  background: var(--border-strong);
  padding: 2px 8px;
  border-radius: 4px;
}

.suggestion-empty {
  padding: 10px 12px;
  color: var(--text-secondary);
  font-size: 13px;
  text-align: center;
}

.error-text {
  color: #f44336;
  font-size: 13px;
  margin: -8px 0 16px 0;
}

.hint-text {
  color: var(--text-secondary);
  font-size: 12px;
  margin: 6px 0 0 0;
  line-height: 1.5;
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
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-secondary:hover {
  background: var(--bg-surface-2);
}

.btn-primary {
  padding: 10px 20px;
  background: var(--accent);
  border: none;
  border-radius: 6px;
  color: var(--text-on-accent);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.btn-primary:hover {
  background: var(--accent-active);
}

.btn-danger {
  padding: 10px 20px;
  background: #f44336;
  border: none;
  border-radius: 6px;
  color: var(--text-on-accent);
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
  color: var(--text-primary);
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

/* 标签列表中的补充项预览 */
.tag-qualifiers {
  display: inline-flex;
  gap: 4px;
  margin-left: 6px;
  flex-wrap: wrap;
  vertical-align: middle;
}
.tag-qualifiers .q-chip {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 8px;
  background: var(--accent-soft);
  color: var(--accent);
}

/* 批量管理 */
.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.batch-toggle-btn {
  padding: 12px 20px;
  background: var(--bg-surface-2);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.batch-toggle-btn:hover {
  background: var(--bg-surface-hover);
}

.batch-toggle-btn.active {
  background: var(--accent-active);
  border-color: #1976D2;
}

.batch-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 14px 18px;
  background: var(--info-soft);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  margin-bottom: 20px;
}

.batch-select-all {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: var(--text-secondary);
  cursor: pointer;
}

.batch-actions {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.batch-btn {
  padding: 9px 16px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--bg-surface-hover);
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.batch-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover);
}

.batch-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.batch-btn.move {
  border-color: #1976D2;
}

.batch-btn.merge {
  border-color: #4CAF50;
}

.batch-btn.danger {
  border-color: #f44336;
}

.batch-check {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  flex-shrink: 0;
}

.batch-check input {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

@media (max-width: 768px) {
  .header-actions {
    flex-direction: row;
    align-items: stretch;
    justify-content: flex-start;
    flex-wrap: wrap;
    gap: 8px;
  }
  .batch-toggle-btn,
  .create-btn {
    padding: 8px 14px;
    font-size: 13px;
    flex: 1 1 40%;
    justify-content: center;
    min-width: 0;
  }
  .batch-bar {
    flex-direction: column;
    align-items: stretch;
  }
  .page-header {
    flex-direction: column;
    align-items: stretch;
    gap: 12px;
  }
  .page-header > div:first-child {
    text-align: left;
  }
}
</style>
