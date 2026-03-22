<script setup lang="ts">
import { ref, onMounted, watch, computed } from 'vue'
import { useUserStore } from '../stores/userStore'
import { useVideoStore } from '../stores/videoStore'
import api from '../api'
import { thumbnailApi } from '../api'

const userStore = useUserStore()
const videoStore = useVideoStore()

// 当前活动标签页 —— 使用 sessionStorage 持久化，防止手机切后台后状态丢失
const ADMIN_TAB_KEY = 'admin_active_tab'
const activeTab = ref(sessionStorage.getItem(ADMIN_TAB_KEY) || 'dashboard')

// 监听 activeTab 变化，自动写入 sessionStorage
watch(activeTab, (val) => {
  sessionStorage.setItem(ADMIN_TAB_KEY, val)
})

// 系统信息
const systemInfo = ref<any>(null)
const systemStats = ref<any>(null)
const systemPaths = ref<any>(null)
const loading = ref({
  info: false,
  stats: false,
  paths: false,
  sync: false,
  videos: false,
  users: false,
  libraries: false
})

// 开发同步状态
const syncStatus = ref<any>(null)
const syncLog = ref<string[]>([])
const isSyncing = ref(false)

// 视频管理
const videos = ref<any[]>([])
const videoSearch = ref('')
const videoPage = ref(1)
const videoTotal = ref(0)
const videoLibraryFilter = ref<number | ''>('')  // 当前筛选的视频库ID，空字符串表示全部
const selectedVideos = ref<string[]>([])
const editingVideo = ref<any>(null)
const showVideoEditModal = ref(false)
const showPriorityModal = ref(false)
const batchPriorityValue = ref(50)

// 排序选项（不使用推荐）
const sortOptions = [
  { value: 'name', label: '视频名' },
  { value: 'created_at', label: '文件时间' },
  { value: 'view_count', label: '播放量' },
  { value: 'priority', label: '优先级' },
  { value: 'like_count', label: '点赞数' },
  { value: 'download_count', label: '下载数' },
  { value: 'file_size', label: '文件大小' }
]
const videoSortBy = ref('created_at')  // 默认按文件时间
const videoSortOrder = ref('desc')     // 默认倒序

// 用户管理
const users = ref<any[]>([])
const showUserModal = ref(false)
const editingUser = ref<any>(null)
const userForm = ref({
  username: '',
  password: '',
  role: 'user'
})

// 系统配置
const systemConfig = ref({
  max_upload_size: 1024,
  thumbnail_quality: 85,
  auto_sync: true,
  allow_register: false
})

// 视频库管理
const libraries = ref<any[]>([])
const showLibraryModal = ref(false)
const showPermissionModal = ref(false)
const editingLibrary = ref<any>(null)
const libraryPermissions = ref<any[]>([])
const selectedLibraryId = ref<number | null>(null)
const creatingLibrary = ref(false)
const libraryForm = ref({
  name: '',
  description: '',
  db_file: '',
  config: {}
})
const permissionForm = ref({
  user_id: null as number | null,
  group_id: null as number | null,
  role: 'user',
  access_level: 'read',
  permissions: [] as string[]
})

// 用户组
const userGroups = ref<any[]>([])

// 批量导入
const showImportModal = ref(false)
// 从 sessionStorage 恢复 importFolder，防止切后台后丢失
const importFolder = ref(sessionStorage.getItem('admin_import_folder') || '')
const importRecursive = ref(true)
const scanning = ref(false)
// 从 sessionStorage 恢复扫描结果
const _storedScanned = sessionStorage.getItem('admin_scanned_videos')
const scannedVideos = ref<any[]>(_storedScanned ? JSON.parse(_storedScanned) : [])
const _storedSelected = sessionStorage.getItem('admin_selected_import')
const selectedImportVideos = ref<string[]>(_storedSelected ? JSON.parse(_storedSelected) : [])
const importing = ref(false)
const importProgress = ref({ imported: 0, skipped: 0, failed: 0 })
const importErrors = ref<string[]>([])

// 持久化 importFolder 和扫描结果到 sessionStorage
watch(importFolder, (val) => { sessionStorage.setItem('admin_import_folder', val) })
watch(scannedVideos, (val) => { sessionStorage.setItem('admin_scanned_videos', JSON.stringify(val)) }, { deep: true })
watch(selectedImportVideos, (val) => { sessionStorage.setItem('admin_selected_import', JSON.stringify(val)) }, { deep: true })
const targetLibrary = ref<number | null>(null)
const importDefaultTags = ref('本地视频')

// 文件夹浏览器
const showFolderBrowser = ref(false)
const browserPath = ref('')
const browserFolders = ref<any[]>([])
const browserLoading = ref(false)
const browserHistory = ref<string[]>([])

// 权限级别选项
const accessLevelOptions = [
  { value: 'full', label: '完全访问' },
  { value: 'write', label: '可读写' },
  { value: 'read', label: '只读' },
  { value: 'custom', label: '自定义' }
]

// 获取所有视频库
const fetchLibraries = async () => {
  loading.value.libraries = true
  try {
    const res = await api.get('/api/admin/libraries') as any
    if (res.success) {
      libraries.value = res.data
    }
  } catch (error) {
    console.error('获取视频库列表失败:', error)
  } finally {
    loading.value.libraries = false
  }
}

// 创建视频库
const createLibrary = async () => {
  if (!libraryForm.value.name.trim()) {
    showToast('请输入视频库名称')
    return
  }
  try {
    creatingLibrary.value = true
    const res = await api.post('/api/admin/libraries', libraryForm.value) as any
    if (res.success) {
      showToast('视频库创建成功')
      showLibraryModal.value = false
      libraryForm.value = { name: '', description: '', db_file: '', config: {} }
      fetchLibraries()
    } else {
      showToast(res.message || '创建失败')
    }
  } catch (error: any) {
    console.error('创建视频库失败:', error)
    showToast(error.response?.data?.message || '创建失败')
  } finally {
    creatingLibrary.value = false
  }
}

// 更新视频库
const updateLibrary = async () => {
  if (!editingLibrary.value) return
  try {
    const res = await api.put(`/api/admin/libraries/${editingLibrary.value.id}`, editingLibrary.value) as any
    if (res.success) {
      showToast('更新成功')
      showLibraryModal.value = false
      editingLibrary.value = null
      fetchLibraries()
    }
  } catch (error) {
    console.error('更新视频库失败:', error)
    showToast('更新失败')
  }
}

// 删除视频库
const deleteLibrary = async (id: number) => {
  if (!confirm('确定要删除该视频库吗？')) return
  try {
    const res = await api.delete(`/api/admin/libraries/${id}`) as any
    if (res.success) {
      showToast('删除成功')
      fetchLibraries()
    }
  } catch (error) {
    console.error('删除视频库失败:', error)
    showToast('删除失败')
  }
}

// 切换视频库激活状态
const toggleLibraryActive = async (lib: any) => {
  try {
    const newStatus = !lib.is_active
    const res = await api.put(`/api/admin/libraries/${lib.id}`, {
      ...lib,
      is_active: newStatus
    }) as any
    if (res.success) {
      showToast(newStatus ? '视频库已激活' : '视频库已禁用')
      fetchLibraries()
    }
  } catch (error) {
    console.error('切换视频库状态失败:', error)
    showToast('操作失败')
  }
}

// 编辑视频库
const editLibrary = (lib: any) => {
  editingLibrary.value = { ...lib }
  showLibraryModal.value = true
}

// 获取视频库权限
const fetchLibraryPermissions = async (libraryId: number) => {
  selectedLibraryId.value = libraryId
  try {
    const res = await api.get(`/api/admin/libraries/${libraryId}/permissions`) as any
    if (res.success) {
      libraryPermissions.value = res.data
    }
  } catch (error) {
    console.error('获取权限列表失败:', error)
  }
}

// 添加权限
const addPermission = async () => {
  if (!selectedLibraryId.value) return
  try {
    const res = await api.post(`/api/admin/libraries/${selectedLibraryId.value}/permissions`, {
      user_id: permissionForm.value.user_id,
      group_id: permissionForm.value.group_id,
      role: permissionForm.value.role,
      access_level: permissionForm.value.access_level,
      permissions: permissionForm.value.permissions
    }) as any
    if (res.success) {
      showToast('权限添加成功')
      showPermissionModal.value = false
      permissionForm.value = { user_id: null, group_id: null, role: 'user', access_level: 'read', permissions: [] }
      fetchLibraryPermissions(selectedLibraryId.value)
    }
  } catch (error) {
    console.error('添加权限失败:', error)
    showToast('添加失败')
  }
}

// 删除权限
const deletePermission = async (permId: number) => {
  if (!selectedLibraryId.value || !confirm('确定要删除该权限吗？')) return
  try {
    const res = await api.delete(`/api/admin/libraries/${selectedLibraryId.value}/permissions/${permId}`) as any
    if (res.success) {
      showToast('权限已删除')
      fetchLibraryPermissions(selectedLibraryId.value)
    }
  } catch (error) {
    console.error('删除权限失败:', error)
    showToast('删除失败')
  }
}

// 获取用户组
const fetchUserGroups = async () => {
  try {
    const res = await api.get('/api/admin/user-groups') as any
    if (res.success) {
      userGroups.value = res.data
    }
  } catch (error) {
    console.error('获取用户组失败:', error)
  }
}

// ============ 批量导入功能 ============

// 扫描文件夹
const scanFolder = async () => {
  if (!importFolder.value.trim()) {
    showToast('请输入文件夹路径')
    return
  }

  // 必须先选择目标视频库
  if (!targetLibrary.value) {
    showToast('请先选择目标视频库')
    return
  }

  scanning.value = true
  scannedVideos.value = []
  selectedImportVideos.value = []
  
  try {
    const res = await api.post('/api/admin/scan-folder', {
      folder_path: importFolder.value,
      recursive: importRecursive.value
    }) as any
    
    if (res.success) {
      scannedVideos.value = res.data.videos
      showToast(`发现 ${res.data.total} 个视频（${res.data.new_count} 个新视频，${res.data.existing_count} 个已存在）`)
    } else {
      showToast(res.message || '扫描失败')
    }
  } catch (error: any) {
    console.error('扫描失败:', error)
    // 显示更详细的错误信息
    let errorMsg = '扫描失败'
    if (error.response) {
      errorMsg = error.response.data?.message || error.response.data?.error || `服务器错误 (${error.response.status})`
    } else if (error.request) {
      errorMsg = '无法连接到服务器'
    } else if (error.message) {
      errorMsg = error.message
    }
    showToast(errorMsg)
  } finally {
    scanning.value = false
  }
}

// 全选/取消全选导入视频
const toggleImportSelectAll = () => {
  if (selectedImportVideos.value.length === scannedVideos.value.filter((v: any) => !v.exists).length) {
    selectedImportVideos.value = []
  } else {
    selectedImportVideos.value = scannedVideos.value.filter((v: any) => !v.exists).map((v: any) => v.path)
  }
}

// 导入视频
const importVideos = async () => {
  if (selectedImportVideos.value.length === 0) {
    showToast('请选择要导入的视频')
    return
  }

  // 必须选择目标视频库
  if (!targetLibrary.value) {
    showToast('请选择目标视频库')
    return
  }

  importing.value = true
  importProgress.value = { imported: 0, skipped: 0, failed: 0 }
  importErrors.value = []
  
  try {
    const videosToImport = scannedVideos.value
      .filter((v: any) => selectedImportVideos.value.includes(v.path))
      .map((v: any) => ({
        path: v.path,
        title: v.title,
        tags: importDefaultTags.value.split(',').map((t: string) => t.trim()).filter((t: string) => t)
      }))
    
    const res = await api.post('/api/admin/import-videos', {
      library_id: targetLibrary.value,
      videos: videosToImport,
      skip_existing: true,
      default_tags: importDefaultTags.value.split(',').map((t: string) => t.trim()).filter((t: string) => t)
    }) as any
    
    if (res.success) {
      importProgress.value = res.data
      importErrors.value = res.data.errors || []
      showToast(res.message)
      
      // 刷新视频列表
      if (activeTab.value === 'videos') {
        await fetchVideos()
      }
      
      // 关闭弹窗
      setTimeout(() => {
        showImportModal.value = false
        scannedVideos.value = []
        selectedImportVideos.value = []
        sessionStorage.removeItem('admin_scanned_videos')
        sessionStorage.removeItem('admin_selected_import')
      }, 2000)
    } else {
      showToast(res.message || '导入失败')
    }
  } catch (error: any) {
    console.error('导入失败:', error)
    // 显示更详细的错误信息
    let errorMsg = '导入失败'
    if (error.response) {
      // 服务器返回了错误响应
      errorMsg = error.response.data?.message || error.response.data?.error || `服务器错误 (${error.response.status})`
    } else if (error.request) {
      // 请求已发出但没有收到响应
      errorMsg = '无法连接到服务器'
    } else if (error.message) {
      errorMsg = error.message
    }
    showToast(errorMsg)
  } finally {
    importing.value = false
  }
}

// 打开导入弹窗
const openImportModal = () => {
  showImportModal.value = true
  scannedVideos.value = []
  selectedImportVideos.value = []
  importFolder.value = ''
  importProgress.value = { imported: 0, skipped: 0, failed: 0 }
  importErrors.value = []
}

// ============ 文件夹浏览器功能 ============

// 打开文件夹浏览器
const openFolderBrowser = async () => {
  showFolderBrowser.value = true
  browserPath.value = ''
  browserHistory.value = []
  await loadFolderList('')
}

// 加载文件夹列表
const loadFolderList = async (path: string) => {
  browserLoading.value = true
  try {
    const res = await api.get('/api/admin/browse-folders', {
      params: { path, show_files: false }
    }) as any
    
    if (res.success) {
      browserPath.value = res.data.current_path
      browserFolders.value = res.data.folders
    } else {
      showToast(res.message || '加载文件夹失败')
    }
  } catch (error: any) {
    console.error('加载文件夹失败:', error)
    showToast(error.message || '加载文件夹失败')
  } finally {
    browserLoading.value = false
  }
}

// 进入文件夹或驱动器
const enterFolder = (folder: any) => {
  // 支持 folder 和 drive 两种类型
  if (folder.type === 'folder' || folder.type === 'drive') {
    browserHistory.value.push(browserPath.value)
    loadFolderList(folder.path)
  }
}

// 返回上级目录
const goBack = () => {
  if (browserHistory.value.length > 0) {
    const previousPath = browserHistory.value.pop()!
    loadFolderList(previousPath)
  }
}

// 选择当前文件夹
const selectCurrentFolder = () => {
  importFolder.value = browserPath.value
  showFolderBrowser.value = false
}

// 创建用户组
const createUserGroup = async (name: string, description: string) => {
  try {
    const res = await api.post('/api/admin/user-groups', { name, description }) as any
    if (res.success) {
      showToast('用户组创建成功')
      fetchUserGroups()
    }
  } catch (error) {
    console.error('创建用户组失败:', error)
    showToast('创建失败')
  }
}

// 获取系统信息
const fetchSystemInfo = async () => {
  loading.value.info = true
  try {
    const res = await api.get('/api/system/info') as any
    if (res.success) {
      systemInfo.value = res.info
    }
  } catch (error) {
    console.error('获取系统信息失败:', error)
  } finally {
    loading.value.info = false
  }
}

// 获取系统统计
const fetchSystemStats = async () => {
  loading.value.stats = true
  try {
    const res = await api.get('/api/system/stats') as any
    if (res.success) {
      systemStats.value = res.stats
    }
  } catch (error) {
    console.error('获取系统统计失败:', error)
  } finally {
    loading.value.stats = false
  }
}

// 获取系统路径
const fetchSystemPaths = async () => {
  loading.value.paths = true
  try {
    const res = await api.get('/api/system/paths') as any
    if (res.success) {
      systemPaths.value = res.paths
    }
  } catch (error) {
    console.error('获取系统路径失败:', error)
  } finally {
    loading.value.paths = false
  }
}

// 获取开发同步状态
const fetchSyncStatus = async () => {
  loading.value.sync = true
  try {
    const res = await api.get('/api/system/sync-status') as any
    if (res.success) {
      syncStatus.value = res.status
      syncLog.value = res.log || []
    }
  } catch (error) {
    console.error('获取同步状态失败:', error)
  } finally {
    loading.value.sync = false
  }
}

// 触发全量同步
const triggerFullSync = async () => {
  if (isSyncing.value) return
  
  isSyncing.value = true
  try {
    const res = await api.post('/api/system/sync-trigger') as any
    if (res.success) {
      // 轮询同步状态
      const checkStatus = setInterval(async () => {
        await fetchSyncStatus()
        if (!syncStatus.value?.is_running) {
          clearInterval(checkStatus)
          isSyncing.value = false
        }
      }, 2000)
    }
  } catch (error) {
    console.error('触发同步失败:', error)
    isSyncing.value = false
  }
}

// 获取视频列表（Admin 专用，直接调用 API 支持 library_id 筛选和排序）
const fetchVideos = async (resetPage = true) => {
  if (resetPage) videoPage.value = 1
  loading.value.videos = true
  // 清空选择
  selectedVideos.value = []
  try {
    const params: any = {
      limit: 20,
      offset: (videoPage.value - 1) * 20,
      sort: videoSortBy.value,
      order: videoSortOrder.value
    }
    if (videoSearch.value.trim()) params.search = videoSearch.value.trim()
    if (videoLibraryFilter.value !== '') params.library_id = videoLibraryFilter.value
    const res = await api.get('/api/videos', { params }) as any
    console.log('[Admin fetchVideos] response:', res)
    if (res.success) {
      videos.value = res.videos || []
      videoTotal.value = res.total || 0
      console.log('[Admin fetchVideos] videos[0]:', videos.value[0])
    }
  } catch (error) {
    console.error('获取视频列表失败:', error)
  } finally {
    loading.value.videos = false
  }
}

// 获取用户列表
const fetchUsers = async () => {
  loading.value.users = true
  try {
    const res = await api.get('/api/admin/users') as any
    if (res.success) {
      users.value = res.users || []
    }
  } catch (error) {
    console.error('获取用户列表失败:', error)
  } finally {
    loading.value.users = false
  }
}

// 获取系统配置
const fetchSystemConfig = async () => {
  try {
    const res = await api.get('/api/admin/config') as any
    if (res.success) {
      systemConfig.value = { ...systemConfig.value, ...res.config }
    }
  } catch (error) {
    console.error('获取系统配置失败:', error)
  }
}

// 保存系统配置
const saveSystemConfig = async () => {
  try {
    const res = await api.post('/api/admin/config', systemConfig.value) as any
    if (res.success) {
      showToast('配置已保存')
    }
  } catch (error) {
    console.error('保存系统配置失败:', error)
    showToast('保存失败')
  }
}

// 编辑视频
const editVideo = (video: any) => {
  editingVideo.value = { ...video }
  showVideoEditModal.value = true
}

// 保存视频编辑
const saveVideoEdit = async () => {
  if (!editingVideo.value) return
  try {
    const res = await api.post(`/api/videos/${editingVideo.value.hash}/update`, {
      title: editingVideo.value.title,
      description: editingVideo.value.description,
      priority: editingVideo.value.priority
    }) as any
    if (res.success) {
      showToast('保存成功')
      showVideoEditModal.value = false
      fetchVideos()
    }
  } catch (error) {
    console.error('保存视频失败:', error)
    showToast('保存失败')
  }
}

// 批量设置优先级
const batchSetPriority = async () => {
  if (selectedVideos.value.length === 0) return
  try {
    const res = await api.post('/api/admin/videos/batch-update-priority', {
      hashes: selectedVideos.value,
      priority: batchPriorityValue.value
    }) as any
    if (res.success) {
      showToast(`已更新 ${res.updated_count} 个视频的优先级`)
      showPriorityModal.value = false
      selectedVideos.value = []
      fetchVideos()
    }
  } catch (error) {
    console.error('批量设置优先级失败:', error)
    showToast('设置失败')
  }
}

// 获取优先级颜色
const getPriorityColor = (priority: number) => {
  if (priority >= 80) return '#ff4d4f'
  if (priority >= 60) return '#faad14'
  if (priority >= 40) return '#1890ff'
  if (priority >= 20) return '#52c41a'
  return '#8c8c8c'
}

// 获取优先级标签
const getPriorityLabel = (priority: number) => {
  if (priority >= 80) return '极高'
  if (priority >= 60) return '高'
  if (priority >= 40) return '中'
  if (priority >= 20) return '低'
  return '极低'
}

// 删除视频确认对话框
const showDeleteConfirm = ref(false)
const deletingVideoHash = ref('')
const deletingVideoTitle = ref('')
const deleteFileOption = ref(false)  // 是否同时删除文件

// 打开删除确认对话框
const openDeleteConfirm = (hash: string, title: string) => {
  deletingVideoHash.value = hash
  deletingVideoTitle.value = title
  deleteFileOption.value = false
  showDeleteConfirm.value = true
}

// 删除视频
const deleteVideo = async () => {
  if (!deletingVideoHash.value) return
  showDeleteConfirm.value = false
  try {
    const res = await api.delete(`/api/videos/${deletingVideoHash.value}`, {
      data: { delete_file: deleteFileOption.value }
    }) as any
    if (res.success) {
      showToast('删除成功')
      fetchVideos()
    }
  } catch (error) {
    console.error('删除视频失败:', error)
    showToast('删除失败')
  }
  deletingVideoHash.value = ''
  deletingVideoTitle.value = ''
}

// 缩略图操作相关状态
const showThumbnailModal = ref(false)
const thumbnailVideoHash = ref('')
const thumbnailVideoTitle = ref('')
const thumbnailStatus = ref<'loading' | 'ready' | 'not_found' | 'generating'>('loading')
const thumbnailLoading = ref(false)

// 打开缩略图操作模态框
const openThumbnailModal = async (hash: string, title: string) => {
  thumbnailVideoHash.value = hash
  thumbnailVideoTitle.value = title
  showThumbnailModal.value = true
  await checkThumbnailStatus(hash)
}

// 检查缩略图状态
const checkThumbnailStatus = async (hash: string) => {
  thumbnailLoading.value = true
  try {
    const res = await thumbnailApi.getStatus(hash) as any
    if (res.success) {
      thumbnailStatus.value = res.status
    } else {
      thumbnailStatus.value = 'not_found'
    }
  } catch (e) {
    thumbnailStatus.value = 'not_found'
  }
  thumbnailLoading.value = false
}

// 重新生成缩略图
const regenerateThumbnail = async () => {
  if (!thumbnailVideoHash.value) return
  thumbnailLoading.value = true
  thumbnailStatus.value = 'generating'
  try {
    const res = await thumbnailApi.regenerate(thumbnailVideoHash.value) as any
    if (res.success) {
      showToast('缩略图正在重新生成')
      // 轮询检查状态
      const checkInterval = setInterval(async () => {
        await checkThumbnailStatus(thumbnailVideoHash.value)
        if (thumbnailStatus.value === 'ready' || thumbnailStatus.value === 'not_found') {
          clearInterval(checkInterval)
          thumbnailLoading.value = false
        }
      }, 2000)
    } else {
      showToast(res.message || '生成失败')
      thumbnailLoading.value = false
    }
  } catch (e) {
    showToast('生成失败')
    thumbnailLoading.value = false
  }
}

// 删除缩略图
const deleteThumbnail = async () => {
  if (!thumbnailVideoHash.value) return
  thumbnailLoading.value = true
  try {
    const res = await thumbnailApi.delete(thumbnailVideoHash.value) as any
    if (res.success) {
      showToast('缩略图已删除')
      thumbnailStatus.value = 'not_found'
    } else {
      showToast(res.message || '删除失败')
    }
  } catch (e) {
    showToast('删除失败')
  }
  thumbnailLoading.value = false
}

// 批量删除确认对话框
const showBatchDeleteConfirm = ref(false)
const batchDeleteFileOption = ref(false)  // 是否同时删除文件

// 打开批量删除确认对话框
const openBatchDeleteConfirm = () => {
  if (selectedVideos.value.length === 0) return
  batchDeleteFileOption.value = false
  showBatchDeleteConfirm.value = true
}

// 批量删除视频
const batchDeleteVideos = async () => {
  showBatchDeleteConfirm.value = false
  try {
    const res = await api.post('/api/admin/videos/batch-delete', {
      hashes: selectedVideos.value,
      delete_file: batchDeleteFileOption.value
    }) as any
    if (res.success) {
      showToast('批量删除成功')
      selectedVideos.value = []
      fetchVideos()
    }
  } catch (error) {
    console.error('批量删除失败:', error)
    showToast('批量删除失败')
  }
}

// 切换视频选择
const toggleVideoSelection = (hash: string) => {
  const index = selectedVideos.value.indexOf(hash)
  if (index > -1) {
    selectedVideos.value.splice(index, 1)
  } else {
    selectedVideos.value.push(hash)
  }
}

// 切换导入视频选择
const toggleImportVideoSelection = (path: string) => {
  const index = selectedImportVideos.value.indexOf(path)
  if (index > -1) {
    selectedImportVideos.value.splice(index, 1)
  } else {
    selectedImportVideos.value.push(path)
  }
}

// 全选/取消全选
const toggleSelectAll = () => {
  if (selectedVideos.value.length === videos.value.length) {
    selectedVideos.value = []
  } else {
    selectedVideos.value = videos.value.map(v => v.hash)
  }
}

// 创建用户
const createUser = async () => {
  try {
    const res = await api.post('/api/admin/users', userForm.value) as any
    if (res.success) {
      showToast('创建成功')
      showUserModal.value = false
      fetchUsers()
      userForm.value = { username: '', password: '', role: 'user' }
    }
  } catch (error) {
    console.error('创建用户失败:', error)
    showToast('创建失败')
  }
}

// 编辑用户
const editUser = (user: any) => {
  editingUser.value = user
  userForm.value = {
    username: user.username,
    password: '',
    role: ['guest', 'user', 'admin', 'root'][user.role] || 'user'
  }
  showUserModal.value = true
}

// 更新用户
const updateUser = async () => {
  if (!editingUser.value) return
  try {
    const updateData: any = {
      username: userForm.value.username,
      role: userForm.value.role
    }
    if (userForm.value.password) {
      updateData.password = userForm.value.password
    }
    
    const res = await api.put(`/api/admin/users/${editingUser.value.id}`, updateData) as any
    if (res.success) {
      showToast('更新成功')
      showUserModal.value = false
      editingUser.value = null
      userForm.value = { username: '', password: '', role: 'user' }
      fetchUsers()
    }
  } catch (error) {
    console.error('更新用户失败:', error)
    showToast('更新失败')
  }
}

// 删除用户
const deleteUser = async (id: number) => {
  if (!confirm('确定要删除这个用户吗？')) return
  try {
    const res = await api.delete(`/api/admin/users/${id}`) as any
    if (res.success) {
      showToast('删除成功')
      fetchUsers()
    }
  } catch (error) {
    console.error('删除用户失败:', error)
    showToast('删除失败')
  }
}

// 格式化日期
const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

// 获取角色CSS类名
const getRoleClass = (role: number) => {
  const roleMap: Record<number, string> = {
    0: 'guest',
    1: 'user',
    2: 'admin',
    3: 'root'
  }
  return roleMap[role] || 'user'
}

// 格式化路径（缩短显示）
const formatPath = (path: string, maxLength: number = 50) => {
  if (!path) return '-'
  if (path.length <= maxLength) return path
  return '...' + path.slice(-maxLength + 3)
}

// 格式化文件大小
const formatFileSize = (bytes: number) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(2)} ${units[unitIndex]}`
}

// 计算属性：安装信息
const installInfo = computed(() => {
  return systemInfo.value?.install || null
})

// 计算属性：版本号
const version = computed(() => {
  return systemInfo.value?.version || '2.0.0'
})

// 计算属性：同步状态文本
const syncStatusText = computed(() => {
  if (!syncStatus.value) return '未知'
  if (syncStatus.value.is_running) return '运行中'
  if (syncStatus.value.last_sync) return '已停止'
  return '未启动'
})

// 计算属性：同步状态颜色
const syncStatusColor = computed(() => {
  if (!syncStatus.value) return '#9E9E9E'
  if (syncStatus.value.is_running) return '#4CAF50'
  if (syncStatus.value.last_sync) return '#2196F3'
  return '#9E9E9E'
})

// Toast 提示
const toastMessage = ref('')
const showToastFlag = ref(false)
const showToast = (message: string) => {
  toastMessage.value = message
  showToastFlag.value = true
  setTimeout(() => {
    showToastFlag.value = false
  }, 2000)
}

// 切换标签页
const switchTab = (tab: string) => {
  activeTab.value = tab
  if (tab === 'videos') { fetchLibraries(); fetchVideos() }
  if (tab === 'users') fetchUsers()
  if (tab === 'config') fetchSystemConfig()
  if (tab === 'libraries') {
    fetchLibraries()
    fetchUserGroups()
  }
  if (tab === 'import') {
    fetchLibraries()
  }
}

onMounted(() => {
  fetchSystemInfo()
  fetchSystemStats()
  fetchSystemPaths()
  fetchSyncStatus()
  // 恢复上次的标签页数据
  const restoredTab = activeTab.value
  if (restoredTab === 'videos') { fetchLibraries(); fetchVideos() }
  else if (restoredTab === 'users') fetchUsers()
  else if (restoredTab === 'config') fetchSystemConfig()
  else if (restoredTab === 'libraries') { fetchLibraries(); fetchUserGroups() }
  else if (restoredTab === 'import') fetchLibraries()
})
</script>

<template>
  <div class="admin-page">
    <div class="admin-header">
      <h1>管理后台</h1>
      <div class="user-info">
        <span class="role-badge" :class="{ root: userStore.isRoot }">
          {{ userStore.isRoot ? 'ROOT' : 'ADMIN' }}
        </span>
        <span class="username">{{ userStore.user?.username }}</span>
      </div>
    </div>

    <!-- 标签页导航 -->
    <div class="admin-tabs">
      <button 
        class="tab-btn" 
        :class="{ active: activeTab === 'dashboard' }"
        @click="switchTab('dashboard')"
      >
        📊 仪表板
      </button>
      <button 
        class="tab-btn" 
        :class="{ active: activeTab === 'videos' }"
        @click="switchTab('videos')"
      >
        🎬 视频管理
      </button>
      <button 
        class="tab-btn" 
        :class="{ active: activeTab === 'users' }"
        @click="switchTab('users')"
        v-if="userStore.isRoot"
      >
        👥 用户管理
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'config' }"
        @click="switchTab('config')"
      >
        ⚙️ 系统配置
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'libraries' }"
        @click="switchTab('libraries')"
        v-if="userStore.isRoot"
      >
        📁 视频库管理
      </button>
      <button
        class="tab-btn"
        :class="{ active: activeTab === 'import' }"
        @click="switchTab('import')"
        v-if="userStore.isAdmin"
      >
        📥 批量导入
      </button>
    </div>

    <div class="admin-content">
      <!-- 仪表板标签页 -->
      <div v-if="activeTab === 'dashboard'" class="tab-content">
        <!-- 系统概览卡片 -->
        <div class="card-grid">
          <!-- 版本信息卡片 -->
          <div class="info-card version-card">
            <div class="card-header">
              <h3>版本信息</h3>
              <span class="version-badge">v{{ version }}</span>
            </div>
            <div class="card-body">
              <div class="info-row">
                <span class="label">当前版本</span>
                <span class="value highlight">{{ version }}</span>
              </div>
              <div class="info-row">
                <span class="label">安装时间</span>
                <span class="value">{{ formatDate(installInfo?.install_time) }}</span>
              </div>
              <div class="info-row">
                <span class="label">来源目录</span>
                <span class="value path" :title="installInfo?.source_dir">
                  {{ formatPath(installInfo?.source_dir) }}
                </span>
              </div>
              <div class="info-row">
                <span class="label">运行目录</span>
                <span class="value path" :title="systemInfo?.runtime_dir">
                  {{ formatPath(systemInfo?.runtime_dir) }}
                </span>
              </div>
              <div class="info-row" v-if="installInfo?.is_update">
                <span class="label">升级状态</span>
                <span class="value update-badge">已升级</span>
              </div>
            </div>
          </div>

          <!-- 系统统计卡片 -->
          <div class="info-card stats-card">
            <div class="card-header">
              <h3>系统统计</h3>
            </div>
            <div class="card-body">
              <div class="stat-item">
                <div class="stat-icon video">🎬</div>
                <div class="stat-info">
                  <span class="stat-value">{{ systemStats?.videos || 0 }}</span>
                  <span class="stat-label">视频总数</span>
                </div>
              </div>
              <div class="stat-item">
                <div class="stat-icon tag">🏷️</div>
                <div class="stat-info">
                  <span class="stat-value">{{ systemStats?.tags || 0 }}</span>
                  <span class="stat-label">标签总数</span>
                </div>
              </div>
              <div class="stat-item">
                <div class="stat-icon user">👤</div>
                <div class="stat-info">
                  <span class="stat-value">{{ systemStats?.users || 0 }}</span>
                  <span class="stat-label">用户总数</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 开发同步状态卡片 -->
          <div class="info-card sync-card">
            <div class="card-header">
              <h3>开发同步状态</h3>
              <span class="status-indicator" :style="{ backgroundColor: syncStatusColor }">
                {{ syncStatusText }}
              </span>
            </div>
            <div class="card-body">
              <div class="info-row">
                <span class="label">上次同步</span>
                <span class="value">{{ formatDate(syncStatus?.last_sync) }}</span>
              </div>
              <div class="info-row">
                <span class="label">同步文件数</span>
                <span class="value">{{ syncStatus?.synced_count || 0 }}</span>
              </div>
              <div class="info-row">
                <span class="label">监控模式</span>
                <span class="value">{{ syncStatus?.watch_mode ? '已启用' : '未启用' }}</span>
              </div>
              <div class="sync-actions">
                <button 
                  class="sync-btn" 
                  :class="{ syncing: isSyncing }"
                  @click="triggerFullSync"
                  :disabled="isSyncing"
                >
                  <span class="btn-icon">🔄</span>
                  {{ isSyncing ? '同步中...' : '立即全量同步' }}
                </button>
              </div>
            </div>
          </div>

          <!-- 路径配置卡片 -->
          <div class="info-card paths-card">
            <div class="card-header">
              <h3>路径配置</h3>
            </div>
            <div class="card-body">
              <div class="path-list">
                <div class="path-item" v-for="(path, key) in systemPaths" :key="key">
                  <span class="path-key">{{ key }}</span>
                  <span class="path-value" :title="path">{{ formatPath(path, 40) }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- 同步日志区域 -->
        <div class="sync-log-section" v-if="syncLog.length > 0">
          <div class="section-header">
            <h3>同步日志</h3>
            <span class="log-count">最近 {{ syncLog.length }} 条</span>
          </div>
          <div class="log-container">
            <div 
              class="log-item" 
              v-for="(log, index) in syncLog" 
              :key="index"
              :class="{ error: log.includes('ERROR'), success: log.includes('已同步') }"
            >
              {{ log }}
            </div>
          </div>
        </div>
      </div>

      <!-- 视频管理标签页 -->
      <div v-if="activeTab === 'videos'" class="tab-content">
        <div class="section-header">
          <h3>视频管理</h3>
          <div class="section-actions">
            <!-- 视频库筛选 -->
            <select
              v-model="videoLibraryFilter"
              @change="fetchVideos()"
              class="search-input"
              style="min-width: 140px"
            >
              <option value="">全部视频库</option>
              <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
            </select>
            <!-- 排序选择 -->
            <select
              v-model="videoSortBy"
              @change="fetchVideos()"
              class="search-input"
              style="min-width: 120px"
            >
              <option v-for="opt in sortOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
            </select>
            <!-- 升序/降序 -->
            <select
              v-model="videoSortOrder"
              @change="fetchVideos()"
              class="search-input"
              style="min-width: 80px"
            >
              <option value="desc">降序</option>
              <option value="asc">升序</option>
            </select>
            <!-- 搜索 -->
            <input
              v-model="videoSearch"
              @keyup.enter="fetchVideos()"
              type="text"
              placeholder="搜索视频..."
              class="search-input"
            />
            <button class="action-btn" @click="fetchVideos()">搜索</button>
            <!-- 批量操作 -->
            <button
              class="action-btn"
              @click="showPriorityModal = true"
              :disabled="selectedVideos.length === 0"
            >
              批量设置优先级 ({{ selectedVideos.length }})
            </button>
            <button
              class="action-btn danger"
              @click="openBatchDeleteConfirm"
              :disabled="selectedVideos.length === 0"
            >
              批量删除 ({{ selectedVideos.length }})
            </button>
          </div>
        </div>

        <!-- 加载状态 -->
        <div v-if="loading.videos" class="loading-state">
          <div class="loading-spinner"></div>
          <span>加载中...</span>
        </div>

        <!-- 空状态 -->
        <div v-else-if="videos.length === 0" class="empty-state">
          <div class="empty-icon">📁</div>
          <div class="empty-text">暂无视频</div>
          <div class="empty-hint">请尝试导入视频或调整筛选条件</div>
        </div>

        <!-- 桌面端表格 -->
        <div v-else class="data-table-container video-table-desktop">
          <table class="data-table">
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    :checked="selectedVideos.length === videos.length && videos.length > 0"
                    @change="toggleSelectAll"
                  />
                </th>
                <th>标题</th>
                <th class="sortable">优先级</th>
                <th>大小</th>
                <th>时长</th>
                <th>上传时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="video in videos" :key="video.hash">
                <td>
                  <input
                    type="checkbox"
                    :checked="selectedVideos.includes(video.hash)"
                    @change="toggleVideoSelection(video.hash)"
                  />
                </td>
                <td class="video-title-cell">
                  <img
                    :src="video.thumbnail"
                    class="video-thumb"
                    v-if="video.thumbnail"
                    @error="(e: Event) => (e.target as HTMLImageElement).style.display='none'"
                  />
                  <span>{{ video.title || '(无标题)' }}</span>
                  <small style="color:#999; font-size:11px; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:300px;" :title="video.local_path">{{ video.local_path }}</small>
                </td>
                <td>
                  <span
                    class="priority-badge"
                    :style="{ backgroundColor: getPriorityColor(video.priority || 0) + '20', color: getPriorityColor(video.priority || 0) }"
                  >
                    {{ video.priority || 0 }}
                    <small>({{ getPriorityLabel(video.priority || 0) }})</small>
                  </span>
                </td>
                <td>{{ video.file_size ? formatFileSize(video.file_size) : '-' }}</td>
                <td>{{ video.duration != null ? video.duration + 's' : '-' }}</td>
                <td>{{ formatDate(video.created_at) }}</td>
                <td>
                  <button class="icon-btn" @click="editVideo(video)" title="编辑">✏️</button>
                  <button class="icon-btn" @click="openThumbnailModal(video.hash, video.title)" title="缩略图">🖼️</button>
                  <button class="icon-btn danger" @click="openDeleteConfirm(video.hash, video.title)" title="删除">🗑️</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 手机端卡片列表 - 优化版本 -->
        <div v-if="loading.videos" class="loading-state mobile">
          <div class="loading-spinner"></div>
          <span>加载中...</span>
        </div>
        <div v-else-if="videos.length === 0" class="empty-state mobile">
          <div class="empty-icon">📁</div>
          <div class="empty-text">暂无视频</div>
        </div>
        <div v-else class="video-cards-mobile">
          <!-- 移动端全选工具栏 -->
          <div class="mobile-selection-bar">
            <label class="checkbox-label select-all">
              <input
                type="checkbox"
                :checked="selectedVideos.length === videos.length && videos.length > 0"
                @change="toggleSelectAll"
              />
              <span>{{ selectedVideos.length === videos.length ? '取消全选' : '全选' }}</span>
            </label>
            <span class="selected-count">{{ selectedVideos.length }} 已选</span>
            <button
              v-if="selectedVideos.length > 0"
              class="action-btn danger small"
              @click="openBatchDeleteConfirm"
            >
              批量删除
            </button>
          </div>

          <div v-for="video in videos" :key="video.hash" class="video-card-mobile">
            <!-- 缩略图 -->
            <img
              v-if="video.thumbnail"
              :src="video.thumbnail"
              class="card-thumb"
              :alt="video.title"
              @error="(e: Event) => (e.target as HTMLImageElement).style.display='none'"
            />
            <div v-else class="card-thumb card-thumb-placeholder">📹</div>

            <!-- 卡片内容 -->
            <div class="card-content">
              <div class="card-header">
                <input
                  type="checkbox"
                  class="card-checkbox"
                  :checked="selectedVideos.includes(video.hash)"
                  @change="toggleVideoSelection(video.hash)"
                />
                <span class="card-title">{{ video.title || '(无标题)' }}</span>
              </div>

              <!-- 元信息 -->
              <div class="card-meta">
                <span class="card-priority"
                  :style="{ backgroundColor: getPriorityColor(video.priority || 0) + '20', color: getPriorityColor(video.priority || 0) }">
                  P{{ video.priority || 0 }}
                </span>
                <span>📦 {{ video.file_size ? formatFileSize(video.file_size) : '-' }}</span>
                <span>📅 {{ formatDate(video.created_at) }}</span>
              </div>

              <div class="card-path" :title="video.local_path">{{ video.local_path }}</div>

              <div class="card-actions">
                <button class="action-btn" @click="editVideo(video)">编辑</button>
                <button class="action-btn" @click="openThumbnailModal(video.hash, video.title)">缩略图</button>
                <button class="action-btn danger" @click="openDeleteConfirm(video.hash, video.title)">删除</button>
              </div>
            </div>
          </div>
        </div>

        <!-- 分页组件 -->
        <div v-if="videoTotal > 20" class="pagination">
          <button
            class="page-btn"
            :disabled="videoPage <= 1"
            @click="videoPage--; fetchVideos(false)"
          >
            上一页
          </button>
          <span class="page-info">
            第 {{ videoPage }} / {{ Math.ceil(videoTotal / 20) }} 页
            (共 {{ videoTotal }} 条)
          </span>
          <button
            class="page-btn"
            :disabled="videoPage >= Math.ceil(videoTotal / 20)"
            @click="videoPage++; fetchVideos(false)"
          >
            下一页
          </button>
        </div>
      </div>

      <!-- 用户管理标签页 -->
      <div v-if="activeTab === 'users'" class="tab-content">
        <div class="section-header">
          <h3>用户管理</h3>
          <button class="action-btn primary" @click="showUserModal = true">+ 添加用户</button>
        </div>

        <div class="data-table-container">
          <table class="data-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>用户名</th>
                <th>角色</th>
                <th>创建时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="user in users" :key="user.id">
                <td>{{ user.id }}</td>
                <td>{{ user.username }}</td>
                <td>
                  <span class="role-tag" :class="getRoleClass(user.role)">{{ user.role_name }}</span>
                </td>
                <td>{{ formatDate(user.created_at) }}</td>
                <td>
                  <button 
                    class="icon-btn" 
                    @click="editUser(user)"
                    v-if="user.id !== userStore.user?.id"
                  >
                    ✏️
                  </button>
                  <button 
                    class="icon-btn danger" 
                    @click="deleteUser(user.id)"
                    v-if="user.id !== userStore.user?.id"
                  >
                    🗑️
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 系统配置标签页 -->
      <div v-if="activeTab === 'config'" class="tab-content">
        <div class="section-header">
          <h3>系统配置</h3>
        </div>

        <div class="config-form">
          <div class="form-group">
            <label>最大上传大小 (MB)</label>
            <input 
              v-model.number="systemConfig.max_upload_size" 
              type="number" 
              min="1"
              max="10240"
            />
          </div>
          <div class="form-group">
            <label>缩略图质量 (1-100)</label>
            <input 
              v-model.number="systemConfig.thumbnail_quality" 
              type="number" 
              min="1"
              max="100"
            />
          </div>
          <div class="form-group">
            <label>自动同步</label>
            <label class="switch">
              <input v-model="systemConfig.auto_sync" type="checkbox" />
              <span class="slider"></span>
            </label>
          </div>
          <div class="form-group">
            <label>允许注册</label>
            <label class="switch">
              <input v-model="systemConfig.allow_register" type="checkbox" />
              <span class="slider"></span>
            </label>
          </div>
          <div class="form-actions">
            <button class="action-btn primary" @click="saveSystemConfig">保存配置</button>
          </div>
        </div>
      </div>

      <!-- 视频库管理标签页 -->
      <div v-if="activeTab === 'libraries'" class="tab-content">
        <div class="section-header">
          <h3>视频库管理</h3>
          <button class="action-btn primary" @click="editingLibrary = null; showLibraryModal = true">+ 新建视频库</button>
        </div>

        <!-- 视频库列表 -->
        <div class="library-grid">
          <div v-for="lib in libraries" :key="lib.id" class="library-card">
            <div class="library-card-header">
              <h4>{{ lib.name }}</h4>
              <!-- 右上角激活/禁用按钮 -->
              <button
                :class="['toggle-active-btn', lib.is_active ? 'active' : 'inactive']"
                @click="toggleLibraryActive(lib)"
                :title="lib.is_active ? '点击禁用' : '点击激活'"
              >
                {{ lib.is_active ? '✓ 激活' : '✗ 禁用' }}
              </button>
            </div>
            <div class="library-card-body">
              <p class="library-desc">{{ lib.description || '暂无描述' }}</p>
              <div class="library-stats">
                <span>📄 视频: {{ lib.video_count || 0 }}</span>
                <span>👥 用户: {{ lib.user_count || 0 }}</span>
              </div>
              <p class="library-path">路径: {{ lib.db_path }}/{{ lib.db_file }}</p>
            </div>
            <div class="library-card-actions">
              <button class="action-btn" @click="editLibrary(lib)">编辑</button>
              <button class="action-btn" @click="fetchLibraryPermissions(lib.id); showPermissionModal = true">权限</button>
              <button class="action-btn danger" @click="deleteLibrary(lib.id)">删除</button>
            </div>
          </div>
        </div>

        <div v-if="libraries.length === 0 && !loading.libraries" class="empty-state">
          <p>暂无视频库，请创建一个</p>
        </div>
      </div>

      <!-- 批量导入标签页 -->
      <div v-if="activeTab === 'import'" class="tab-content">
        <div class="section-header">
          <h3>📥 批量导入视频</h3>
        </div>

        <div class="import-container">
          <!-- 扫描配置 -->
          <div class="import-config card">
            <h4>扫描配置</h4>
            <div class="form-group">
              <label>文件夹路径 <span class="required">*</span></label>
              <input
                v-model="importFolder"
                type="text"
                placeholder="例如：D:\Videos 或 M:\Movies"
                class="folder-input"
              />
              <small class="form-hint">支持递归扫描子文件夹中的所有视频文件</small>
            </div>

            <div class="form-actions">
              <button
                class="action-btn"
                @click="openFolderBrowser"
                title="浏览文件夹"
              >
                📂 浏览
              </button>
              <button
                class="action-btn primary"
                @click="scanFolder"
                :disabled="scanning || !importFolder.trim()"
              >
                {{ scanning ? '扫描中...' : '🔍 扫描文件夹' }}
              </button>
            </div>

            <div class="form-row">
              <div class="form-group">
                <label>递归扫描</label>
                <label class="checkbox-label">
                  <input v-model="importRecursive" type="checkbox" />
                  <span>包含子文件夹</span>
                </label>
              </div>

              <div class="form-group">
                <label>目标视频库 <span class="required">*</span></label>
                <select v-model.number="targetLibrary" required>
                  <option :value="null" disabled>请选择视频库</option>
                  <option v-for="lib in libraries" :key="lib.id" :value="lib.id">
                    {{ lib.name }}
                  </option>
                </select>
              </div>

              <div class="form-group">
                <label>默认标签</label>
                <input 
                  v-model="importDefaultTags" 
                  type="text" 
                  placeholder="用逗号分隔多个标签，如：本地视频,电影"
                />
              </div>
            </div>
          </div>

          <!-- 扫描结果 -->
          <div v-if="scannedVideos.length > 0" class="scan-results card">
            <div class="results-header">
              <h4>扫描结果 ({{ scannedVideos.length }} 个视频)</h4>
            </div>

            <div class="results-toolbar">
              <label class="checkbox-label select-all">
                <input
                  type="checkbox"
                  :checked="selectedImportVideos.length > 0 && selectedImportVideos.length === scannedVideos.filter((v: any) => !v.exists).length"
                  :indeterminate="selectedImportVideos.length > 0 && selectedImportVideos.length < scannedVideos.filter((v: any) => !v.exists).length"
                  @change="toggleImportSelectAll"
                />
                <span>{{ selectedImportVideos.length === scannedVideos.filter((v: any) => !v.exists).length ? '取消全选' : '全选' }}</span>
              </label>
              <span class="selected-count">
                已选择 {{ selectedImportVideos.length }} / {{ scannedVideos.filter((v: any) => !v.exists).length }} 个新视频
              </span>
            </div>

            <div class="video-list">
              <div 
                v-for="video in scannedVideos" 
                :key="video.path"
                :class="['video-item', { 
                  selected: selectedImportVideos.includes(video.path),
                  existing: video.exists 
                }]"
                @click="!video.exists && toggleImportVideoSelection(video.path)"
              >
                <div class="video-checkbox">
                  <input 
                    v-if="!video.exists"
                    type="checkbox" 
                    :checked="selectedImportVideos.includes(video.path)"
                    @click.stop
                    @change="toggleImportVideoSelection(video.path)"
                  />
                  <span v-else class="exists-badge">已存在</span>
                </div>
                <div class="video-info">
                  <div class="video-title">{{ video.title }}</div>
                  <div class="video-meta">
                    <span>📁 {{ video.path }}</span>
                    <span>💾 {{ video.size_mb }} MB</span>
                  </div>
                </div>
              </div>
            </div>

            <div class="import-actions">
              <button 
                class="action-btn primary large"
                @click="importVideos"
                :disabled="importing || selectedImportVideos.length === 0"
              >
                {{ importing ? '导入中...' : `导入 ${selectedImportVideos.length} 个视频` }}
              </button>
            </div>
          </div>

          <!-- 导入进度 -->
          <div v-if="importing || importProgress.imported > 0" class="import-progress card">
            <h4>导入进度</h4>
            <div class="progress-stats">
              <div class="stat-item success">
                <span class="stat-label">已导入</span>
                <span class="stat-value">{{ importProgress.imported }}</span>
              </div>
              <div class="stat-item warning">
                <span class="stat-label">已跳过</span>
                <span class="stat-value">{{ importProgress.skipped }}</span>
              </div>
              <div class="stat-item error">
                <span class="stat-label">失败</span>
                <span class="stat-value">{{ importProgress.failed }}</span>
              </div>
            </div>
            
            <div v-if="importErrors.length > 0" class="import-errors">
              <h5>错误信息</h5>
              <ul>
                <li v-for="(error, idx) in importErrors" :key="idx">{{ error }}</li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 视频编辑弹窗 -->
    <div v-if="showVideoEditModal" class="modal-overlay" @click="showVideoEditModal = false">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>编辑视频</h3>
          <button class="close-btn" @click="showVideoEditModal = false">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>标题</label>
            <input v-model="editingVideo.title" type="text" />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea v-model="editingVideo.description" rows="4"></textarea>
          </div>
          <div class="form-group">
            <label>优先级 (0-100)</label>
            <div class="priority-input-group">
              <input 
                v-model.number="editingVideo.priority" 
                type="number" 
                min="0" 
                max="100"
                class="priority-input"
              />
              <input 
                v-model.number="editingVideo.priority" 
                type="range" 
                min="0" 
                max="100"
                class="priority-slider"
              />
              <span 
                class="priority-preview" 
                :style="{ color: getPriorityColor(editingVideo.priority || 0) }"
              >
                {{ getPriorityLabel(editingVideo.priority || 0) }}
              </span>
            </div>
            <small class="form-hint">优先级越高，视频在推荐中的排名越靠前</small>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showVideoEditModal = false">取消</button>
          <button class="action-btn primary" @click="saveVideoEdit">保存</button>
        </div>
      </div>
    </div>

    <!-- 批量设置优先级弹窗 -->
    <div v-if="showPriorityModal" class="modal-overlay" @click="showPriorityModal = false">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>批量设置优先级</h3>
          <button class="close-btn" @click="showPriorityModal = false">×</button>
        </div>
        <div class="modal-body">
          <p class="modal-info">已选择 {{ selectedVideos.length }} 个视频</p>
          <div class="form-group">
            <label>优先级 (0-100)</label>
            <div class="priority-input-group">
              <input 
                v-model.number="batchPriorityValue" 
                type="number" 
                min="0" 
                max="100"
                class="priority-input"
              />
              <input 
                v-model.number="batchPriorityValue" 
                type="range" 
                min="0" 
                max="100"
                class="priority-slider"
              />
              <span 
                class="priority-preview" 
                :style="{ color: getPriorityColor(batchPriorityValue) }"
              >
                {{ getPriorityLabel(batchPriorityValue) }}
              </span>
            </div>
            <small class="form-hint">优先级越高，视频在推荐中的排名越靠前</small>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showPriorityModal = false">取消</button>
          <button class="action-btn primary" @click="batchSetPriority">确认设置</button>
        </div>
      </div>
    </div>

    <!-- 视频库编辑弹窗 -->
    <div v-if="showLibraryModal" class="modal-overlay" @click="showLibraryModal = false">
      <div class="modal-content library-modal" @click.stop>
        <div class="modal-header">
          <h3>{{ editingLibrary ? '✏️ 编辑视频库' : '📁 新建视频库' }}</h3>
          <button class="close-btn" @click="showLibraryModal = false">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>视频库名称 <span class="required">*</span></label>
            <input 
              v-if="editingLibrary" 
              v-model="editingLibrary.name" 
              type="text" 
              placeholder="请输入视频库名称"
            />
            <input 
              v-else 
              v-model="libraryForm.name" 
              type="text" 
              placeholder="例如：经典电影库、4K高清专区"
              autofocus
            />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea 
              v-if="editingLibrary" 
              v-model="editingLibrary.description" 
              rows="4"
              placeholder="请输入视频库描述（可选）"
            ></textarea>
            <textarea 
              v-else 
              v-model="libraryForm.description" 
              rows="4"
              placeholder="例如：收录经典老电影、动作片专区等"
            ></textarea>
          </div>
          <div class="form-tip" v-if="!editingLibrary">
            <span class="tip-icon">💡</span>
            <span>数据库文件将自动创建，无需手动指定</span>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn btn-secondary" @click="showLibraryModal = false">取消</button>
          <button 
            class="btn btn-primary" 
            @click="editingLibrary ? updateLibrary() : createLibrary()"
            :disabled="creatingLibrary || (!editingLibrary && !libraryForm.name.trim())"
          >
            <span v-if="creatingLibrary">创建中...</span>
            <span v-else>{{ editingLibrary ? '保存修改' : '创建视频库' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 权限配置弹窗 -->
    <div v-if="showPermissionModal" class="modal-overlay" @click="showPermissionModal = false">
      <div class="modal-content modal-large" @click.stop>
        <div class="modal-header">
          <h3>权限配置</h3>
          <button class="close-btn" @click="showPermissionModal = false">×</button>
        </div>
        <div class="modal-body">
          <!-- 添加权限表单 -->
          <div class="permission-form">
            <h4>添加权限</h4>
            <div class="form-row">
              <div class="form-group">
                <label>用户ID</label>
                <input v-model.number="permissionForm.user_id" type="number" placeholder="用户ID" />
              </div>
              <div class="form-group">
                <label>或用户组</label>
                <select v-model.number="permissionForm.group_id">
                  <option :value="null">-- 选择用户组 --</option>
                  <option v-for="g in userGroups" :key="g.id" :value="g.id">{{ g.name }}</option>
                </select>
              </div>
            </div>
            <div class="form-row">
              <div class="form-group">
                <label>角色</label>
                <select v-model="permissionForm.role">
                  <option value="user">普通用户</option>
                  <option value="admin">库管理员</option>
                </select>
              </div>
              <div class="form-group">
                <label>访问级别</label>
                <select v-model="permissionForm.access_level">
                  <option v-for="opt in accessLevelOptions" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
                </select>
              </div>
            </div>
            <button class="action-btn primary" @click="addPermission">添加权限</button>
          </div>

          <!-- 权限列表 -->
          <div class="permission-list">
            <h4>现有权限</h4>
            <table class="data-table">
              <thead>
                <tr>
                  <th>类型</th>
                  <th>用户/用户组</th>
                  <th>角色</th>
                  <th>访问级别</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="perm in libraryPermissions" :key="perm.id">
                  <td>{{ perm.user_id ? '用户' : '用户组' }}</td>
                  <td>{{ perm.user?.username || perm.group?.name || perm.user_id || perm.group_id }}</td>
                  <td>{{ perm.role === 'admin' ? '管理员' : '用户' }}</td>
                  <td>{{ accessLevelOptions.find(o => o.value === perm.access_level)?.label || perm.access_level }}</td>
                  <td>
                    <button class="action-btn danger" @click="deletePermission(perm.id)">删除</button>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="libraryPermissions.length === 0" class="empty-state">
              <p>暂无权限配置</p>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showPermissionModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 文件夹浏览器弹窗 -->
    <div v-if="showFolderBrowser" class="modal-overlay" @click="showFolderBrowser = false">
      <div class="modal-content folder-browser-modal" @click.stop>
        <div class="modal-header">
          <h3>📂 选择文件夹</h3>
          <button class="close-btn" @click="showFolderBrowser = false">×</button>
        </div>
        <div class="modal-body">
          <!-- 当前路径 -->
          <div class="current-path-display">
            <span class="path-label">当前路径：</span>
            <span class="path-value">{{ browserPath || '根目录' }}</span>
          </div>

          <!-- 导航栏 -->
          <div class="browser-nav">
            <button 
              class="nav-btn" 
              @click="goBack"
              :disabled="browserHistory.length === 0"
              title="返回上级"
            >
              ⬅️ 返回上级
            </button>
            <button 
              class="nav-btn" 
              @click="loadFolderList('')"
              title="回到根目录"
            >
              🏠 根目录
            </button>
          </div>

          <!-- 文件夹列表 -->
          <div class="folder-list-container">
            <div v-if="browserLoading" class="loading-state">
              <div class="loading-spinner"></div>
              <p>加载中...</p>
            </div>

            <div v-else-if="browserFolders.length === 0" class="empty-state">
              <p>此文件夹为空或无法访问</p>
            </div>

            <div v-else class="folder-list">
              <div 
                v-for="item in browserFolders" 
                :key="item.path"
                class="folder-item"
                @click="enterFolder(item)"
              >
                <div class="folder-icon">
                  {{ item.type === 'drive' ? '💿' : '📁' }}
                </div>
                <div class="folder-info">
                  <div class="folder-name">{{ item.display || item.name }}</div>
                  <div class="folder-type">{{ item.type === 'drive' ? '驱动器' : '文件夹' }}</div>
                </div>
                <div class="folder-arrow">▶</div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showFolderBrowser = false">取消</button>
          <button 
            class="action-btn primary" 
            @click="selectCurrentFolder"
            :disabled="!browserPath"
          >
            选择此文件夹
          </button>
        </div>
      </div>
    </div>

    <!-- 用户创建/编辑弹窗 -->
    <div v-if="showUserModal" class="modal-overlay" @click="showUserModal = false">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>{{ editingUser ? '编辑用户' : '添加用户' }}</h3>
          <button class="close-btn" @click="showUserModal = false">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>用户名</label>
            <input v-model="userForm.username" type="text" />
          </div>
          <div class="form-group">
            <label>密码{{ editingUser ? '（留空表示不修改）' : '' }}</label>
            <input v-model="userForm.password" type="password" :placeholder="editingUser ? '留空表示不修改密码' : ''" />
          </div>
          <div class="form-group">
            <label>角色</label>
            <select v-model="userForm.role">
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
              <option value="root">超级管理员</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showUserModal = false">取消</button>
          <button class="action-btn primary" @click="editingUser ? updateUser() : createUser()">
            {{ editingUser ? '保存' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 删除单个视频确认对话框 -->
    <div v-if="showDeleteConfirm" class="dialog-overlay" @click.self="showDeleteConfirm = false">
      <div class="dialog">
        <h3>确认删除</h3>
        <p>确定要删除视频「<strong>{{ deletingVideoTitle }}</strong>」吗？</p>
        <div class="dialog-checkbox">
          <label>
            <input type="checkbox" v-model="deleteFileOption" />
            同时删除视频文件（不可恢复）
          </label>
        </div>
        <div class="dialog-buttons">
          <button class="btn-secondary" @click="showDeleteConfirm = false">取消</button>
          <button class="btn-danger" @click="deleteVideo">删除</button>
        </div>
      </div>
    </div>

    <!-- 批量删除确认对话框 -->
    <div v-if="showBatchDeleteConfirm" class="dialog-overlay" @click.self="showBatchDeleteConfirm = false">
      <div class="dialog">
        <h3>确认批量删除</h3>
        <p>确定要删除选中的 <strong>{{ selectedVideos.length }}</strong> 个视频吗？</p>
        <div class="dialog-checkbox">
          <label>
            <input type="checkbox" v-model="batchDeleteFileOption" />
            同时删除视频文件（不可恢复）
          </label>
        </div>
        <div class="dialog-buttons">
          <button class="btn-secondary" @click="showBatchDeleteConfirm = false">取消</button>
          <button class="btn-danger" @click="batchDeleteVideos">删除</button>
        </div>
      </div>
    </div>

    <!-- 缩略图操作对话框 -->
    <div v-if="showThumbnailModal" class="dialog-overlay" @click.self="showThumbnailModal = false">
      <div class="dialog thumbnail-dialog">
        <h3>缩略图管理</h3>
        <p class="dialog-video-title">视频：{{ thumbnailVideoTitle }}</p>

        <!-- 缩略图状态显示 -->
        <div class="thumbnail-status">
          <div v-if="thumbnailLoading" class="thumbnail-loading">
            <div class="loading-spinner"></div>
            <span>加载中...</span>
          </div>
          <div v-else-if="thumbnailStatus === 'ready'" class="thumbnail-ready">
            <img
              :src="`/thumbnail/${thumbnailVideoHash}?t=${Date.now()}`"
              class="thumbnail-preview"
              @error="(e: Event) => (e.target as HTMLImageElement).style.display='none'"
            />
            <div class="thumbnail-status-text">✓ 缩略图已生成</div>
          </div>
          <div v-else-if="thumbnailStatus === 'generating'" class="thumbnail-generating">
            <div class="thumbnail-placeholder">
              <span class="placeholder-icon">🖼️</span>
            </div>
            <div class="thumbnail-status-text">正在生成缩略图...</div>
          </div>
          <div v-else class="thumbnail-not-found">
            <div class="thumbnail-placeholder">
              <span class="placeholder-icon">🖼️</span>
            </div>
            <div class="thumbnail-status-text">暂无缩略图</div>
          </div>
        </div>

        <!-- 操作按钮 -->
        <div class="thumbnail-actions">
          <button
            class="action-btn primary"
            @click="regenerateThumbnail"
            :disabled="thumbnailLoading"
          >
            {{ thumbnailStatus === 'ready' ? '重新生成' : '生成缩略图' }}
          </button>
          <button
            v-if="thumbnailStatus === 'ready'"
            class="action-btn danger"
            @click="deleteThumbnail"
            :disabled="thumbnailLoading"
          >
            删除缩略图
          </button>
        </div>

        <div class="dialog-buttons">
          <button class="btn-secondary" @click="showThumbnailModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- Toast 提示 -->
    <div v-if="showToastFlag" class="toast">{{ toastMessage }}</div>
  </div>
</template>

<style scoped>
/* 删除确认对话框 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog {
  background: white;
  border-radius: 12px;
  padding: 24px;
  min-width: 360px;
  max-width: 480px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
}

.dialog h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
  color: #1a1a2e;
}

.dialog p {
  margin: 0 0 16px 0;
  color: #666;
  line-height: 1.5;
}

.dialog-checkbox {
  margin-bottom: 20px;
  padding: 12px;
  background: #f5f5f5;
  border-radius: 8px;
}

.dialog-checkbox label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #333;
  font-size: 14px;
}

.dialog-checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.dialog-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-secondary {
  padding: 8px 16px;
  background: #f0f0f0;
  border: none;
  border-radius: 6px;
  color: #333;
  cursor: pointer;
  font-size: 14px;
}

.btn-secondary:hover {
  background: #e0e0e0;
}

.btn-danger {
  padding: 8px 16px;
  background: #dc3545;
  border: none;
  border-radius: 6px;
  color: white;
  cursor: pointer;
  font-size: 14px;
}

.btn-danger:hover {
  background: #c82333;
}

/* 缩略图对话框样式 */
.thumbnail-dialog {
  min-width: 400px;
  max-width: 90vw;
}

.dialog-video-title {
  font-size: 14px;
  color: #666;
  margin-bottom: 16px;
  padding: 8px 12px;
  background: #f8f9fa;
  border-radius: 6px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.thumbnail-status {
  margin: 20px 0;
  min-height: 180px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.thumbnail-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  color: #666;
}

.thumbnail-ready {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.thumbnail-preview {
  max-width: 280px;
  max-height: 180px;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  object-fit: contain;
}

.thumbnail-status-text {
  font-size: 14px;
  color: #28a745;
}

.thumbnail-generating,
.thumbnail-not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.thumbnail-placeholder {
  width: 200px;
  height: 120px;
  background: linear-gradient(135deg, #f0f0f0 0%, #e0e0e0 100%);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.placeholder-icon {
  font-size: 48px;
  opacity: 0.3;
}

.thumbnail-status-text {
  font-size: 14px;
  color: #999;
}

.thumbnail-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  margin-bottom: 20px;
}

.thumbnail-actions .action-btn {
  flex: 1;
  max-width: 160px;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .thumbnail-dialog {
    min-width: auto;
    width: 90vw;
    padding: 16px;
  }

  .thumbnail-preview {
    max-width: 100%;
    max-height: 150px;
  }

  .thumbnail-actions {
    flex-direction: column;
  }

  .thumbnail-actions .action-btn {
    max-width: 100%;
  }
}

.admin-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #f5f7fa 0%, #e4e8ec 100%);
  padding: 24px;
}

.admin-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding: 16px 24px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.admin-header h1 {
  margin: 0;
  font-size: 24px;
  color: #1a1a2e;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 12px;
}

.role-badge {
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  background: #2196F3;
  color: white;
}

.role-badge.root {
  background: #F44336;
}

.username {
  font-size: 14px;
  color: #666;
}

.admin-content {
  max-width: 1400px;
  margin: 0 auto;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
  margin-bottom: 24px;
}

.info-card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.version-badge {
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.2);
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-indicator {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
  color: white;
}

.card-body {
  padding: 20px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
}

.info-row:last-child {
  border-bottom: none;
}

.label {
  font-size: 13px;
  color: #666;
}

.value {
  font-size: 13px;
  color: #333;
  font-weight: 500;
}

.value.highlight {
  color: #667eea;
  font-size: 16px;
  font-weight: 700;
}

.value.path {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: #666;
}

.update-badge {
  padding: 2px 8px;
  background: #4CAF50;
  color: white;
  border-radius: 4px;
  font-size: 11px;
}

/* 统计卡片样式 */
.stats-card .card-body {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
}

.stat-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: white;
  border-radius: 12px;
  font-size: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-size: 24px;
  font-weight: 700;
  color: #1a1a2e;
}

.stat-label {
  font-size: 12px;
  color: #888;
}

/* 同步卡片样式 */
.sync-actions {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #f0f0f0;
}

.sync-btn {
  width: 100%;
  padding: 12px 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  transition: all 0.3s ease;
}

.sync-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.sync-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

.sync-btn.syncing {
  background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
}

.btn-icon {
  font-size: 16px;
}

.syncing .btn-icon {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 路径配置样式 */
.paths-card {
  grid-column: span 2;
}

.path-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 12px;
}

.path-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
}

.path-key {
  font-size: 11px;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.path-value {
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: #333;
  word-break: break-all;
}

/* 同步日志样式 */
.sync-log-section {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: #f8f9fa;
  border-bottom: 1px solid #e8e8e8;
}

.section-header h3 {
  margin: 0;
  font-size: 16px;
  color: #333;
}

.log-count {
  font-size: 12px;
  color: #888;
}

.log-container {
  max-height: 300px;
  overflow-y: auto;
  padding: 12px;
  background: #1e1e1e;
}

.log-item {
  padding: 6px 12px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: #d4d4d4;
  border-left: 3px solid transparent;
}

.log-item.error {
  color: #f48771;
  border-left-color: #f48771;
  background: rgba(244, 135, 113, 0.1);
}

.log-item.success {
  color: #7ee787;
  border-left-color: #7ee787;
}

/* 标签页导航 */
.admin-tabs {
  display: flex;
  gap: 8px;
  padding: 0 24px 16px;
  background: white;
  border-bottom: 1px solid #e8e8e8;
  margin: 0 -24px 24px;
}

.tab-btn {
  padding: 10px 20px;
  background: transparent;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  color: #666;
  cursor: pointer;
  transition: all 0.3s ease;
}

.tab-btn:hover {
  background: #f5f5f5;
  color: #333;
}

.tab-btn.active {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.tab-content {
  animation: fadeIn 0.3s ease;
}

@keyframes fadeIn {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}

/* 数据表格 */
.section-actions {
  display: flex;
  gap: 12px;
  align-items: center;
}

.search-input {
  padding: 8px 16px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  width: 240px;
}

.data-table-container {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.data-table {
  width: 100%;
  min-width: 600px;  /* 确保小屏幕下表格不会被压缩 */
  border-collapse: collapse;
}

.data-table th,
.data-table td {
  padding: 14px 16px;
  text-align: left;
  border-bottom: 1px solid #f0f0f0;
}

.data-table th {
  background: #f8f9fa;
  font-weight: 600;
  font-size: 13px;
  color: #666;
  position: sticky;
  top: 0;
  z-index: 10;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.data-table th:hover {
  background: #e9ecef;
}

.data-table th.sortable {
  position: relative;
  padding-right: 24px;
}

.data-table th.sortable::after {
  content: '↕';
  position: absolute;
  right: 8px;
  opacity: 0.3;
}

.data-table th.sort-asc::after {
  content: '↑';
  opacity: 1;
  color: #1890ff;
}

.data-table th.sort-desc::after {
  content: '↓';
  opacity: 1;
  color: #1890ff;
}

.data-table td {
  color: #333;
}

.data-table tbody tr {
  transition: background 0.15s ease;
}

.data-table tbody tr:hover {
  background: #f0f7ff;
}

.data-table tbody tr.selected {
  background: #e6f7ff;
}

/* 桌面端默认显示表格，隐藏手机端卡片 */
.video-table-desktop {
  display: block;
}
.video-cards-mobile {
  display: none;
}

.video-title-cell {
  display: flex;
  align-items: center;
  gap: 12px;
}

/* 加载状态 */
.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #999;
  gap: 12px;
}

.loading-state.mobile {
  padding: 40px 20px;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #f0f0f0;
  border-top-color: #1890ff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: #999;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.empty-state.mobile {
  padding: 40px 20px;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.6;
}

.empty-text {
  font-size: 16px;
  color: #666;
  font-weight: 500;
}

.empty-hint {
  font-size: 13px;
  color: #999;
  margin-top: 8px;
}

/* 分页组件 */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 20px;
  margin-top: 16px;
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.page-btn {
  padding: 8px 16px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: white;
  color: #333;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) {
  color: #1890ff;
  border-color: #1890ff;
}

.page-btn:disabled {
  color: #ccc;
  border-color: #f0f0f0;
  cursor: not-allowed;
}

.page-info {
  font-size: 13px;
  color: #666;
}

.video-thumb {
  width: 60px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
}

/* 操作按钮 */
.action-btn {
  padding: 8px 16px;
  background: #f0f0f0;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.action-btn:hover {
  background: #e0e0e0;
}

.action-btn.primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.action-btn.primary:hover {
  opacity: 0.9;
}

.action-btn.danger {
  background: #ff4d4f;
  color: white;
}

.action-btn.danger:hover {
  background: #ff7875;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon-btn {
  padding: 6px 10px;
  background: transparent;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
  transition: all 0.3s ease;
}

.icon-btn:hover {
  background: #f0f0f0;
}

.icon-btn.danger:hover {
  background: #fff1f0;
}

/* 角色标签 */
.role-tag {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.role-tag.root {
  background: #fff1f0;
  color: #cf1322;
}

.role-tag.admin {
  background: #e6f7ff;
  color: #096dd9;
}

.role-tag.user {
  background: #f6ffed;
  color: #389e0d;
}

/* 配置表单 */
.config-form {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  max-width: 600px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
  color: #333;
  font-weight: 500;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #ddd;
  border-radius: 8px;
  font-size: 14px;
  transition: border-color 0.3s ease;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #667eea;
}

/* Switch 开关 */
.switch {
  position: relative;
  display: inline-block;
  width: 50px;
  height: 26px;
}

.switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #ccc;
  transition: .4s;
  border-radius: 26px;
}

.slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 4px;
  bottom: 4px;
  background-color: white;
  transition: .4s;
  border-radius: 50%;
}

input:checked + .slider {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

input:checked + .slider:before {
  transform: translateX(24px);
}

.form-actions {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid #f0f0f0;
}

/* 弹窗 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 12px;
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow: hidden;
  animation: modalIn 0.3s ease;
}

@keyframes modalIn {
  from { opacity: 0; transform: scale(0.9); }
  to { opacity: 1; transform: scale(1); }
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid #f0f0f0;
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
}

.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
  color: #999;
}

.modal-body {
  padding: 20px;
  max-height: 60vh;
  overflow-y: auto;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid #f0f0f0;
}

/* Toast */
.toast {
  position: fixed;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.8);
  color: #fff;
  padding: 12px 24px;
  border-radius: 24px;
  font-size: 14px;
  z-index: 2000;
  animation: fadeInOut 2s ease;
}

@keyframes fadeInOut {
  0% { opacity: 0; transform: translateX(-50%) translateY(20px); }
  10% { opacity: 1; transform: translateX(-50%) translateY(0); }
  90% { opacity: 1; transform: translateX(-50%) translateY(0); }
  100% { opacity: 0; transform: translateX(-50%) translateY(-20px); }
}

/* 优先级样式 */
.priority-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
}

.priority-badge small {
  font-size: 11px;
  opacity: 0.8;
}

.priority-input-group {
  display: flex;
  align-items: center;
  gap: 12px;
}

.priority-input {
  width: 80px !important;
  text-align: center;
  font-weight: 600;
}

.priority-slider {
  flex: 1;
  height: 6px;
  -webkit-appearance: none;
  appearance: none;
  background: #e8e8e8;
  border-radius: 3px;
  outline: none;
}

.priority-slider::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 50%;
  cursor: pointer;
  transition: transform 0.2s;
}

.priority-slider::-webkit-slider-thumb:hover {
  transform: scale(1.1);
}

.priority-preview {
  min-width: 50px;
  text-align: center;
  font-weight: 600;
  font-size: 14px;
}

.form-hint {
  display: block;
  margin-top: 6px;
  color: #888;
  font-size: 12px;
}

.modal-info {
  margin: 0 0 16px 0;
  padding: 12px;
  background: #f0f5ff;
  border-radius: 8px;
  color: #1890ff;
  font-size: 14px;
}

/* 响应式适配 */
@media (max-width: 768px) {
  .admin-page {
    padding: 12px;
  }
  
  .admin-tabs {
    padding: 0 12px 12px;
    margin: 0 -12px 16px;
    overflow-x: auto;
  }
  
  .tab-btn {
    padding: 8px 14px;
    font-size: 13px;
    white-space: nowrap;
  }
  
  .card-grid {
    grid-template-columns: 1fr;
  }
  
  .paths-card {
    grid-column: span 1;
  }
  
  .path-list {
    grid-template-columns: 1fr;
  }
  
  .section-actions {
    flex-wrap: wrap;
  }
  
  .search-input {
    width: 100%;
  }
  
  .data-table {
    font-size: 12px;
  }

  .data-table th,
  .data-table td {
    padding: 10px 8px;
  }

  .video-thumb {
    display: none;
  }

  /* 默认隐藏手机端卡片 */
  .video-cards-mobile {
    display: none;
  }

  /* 手机端卡片式布局 - 优化版本 */
  .video-card-mobile {
    background: white;
    border-radius: 12px;
    padding: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    display: flex;
    gap: 12px;
    transition: transform 0.2s, box-shadow 0.2s;
  }

  .video-card-mobile:active {
    transform: scale(0.98);
  }

  .video-card-mobile .card-thumb {
    width: 80px;
    height: 60px;
    object-fit: cover;
    border-radius: 8px;
    flex-shrink: 0;
    background: #f0f0f0;
  }

  .video-card-mobile .card-thumb-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    color: #ccc;
    background: linear-gradient(135deg, #f5f5f5 0%, #e8e8e8 100%);
  }

  .video-card-mobile .card-content {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .video-card-mobile .card-header {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }

  .video-card-mobile .card-checkbox {
    margin-top: 2px;
    flex-shrink: 0;
  }

  .video-card-mobile .card-title {
    font-weight: 600;
    font-size: 14px;
    color: #333;
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    line-height: 1.4;
  }

  .video-card-mobile .card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 11px;
    color: #888;
  }

  .video-card-mobile .card-meta span {
    display: flex;
    align-items: center;
    gap: 3px;
  }

  .video-card-mobile .card-priority {
    display: inline-flex;
    align-items: center;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 500;
  }

  .video-card-mobile .card-path {
    font-size: 11px;
    color: #999;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .video-card-mobile .card-actions {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    padding-top: 8px;
    border-top: 1px solid #f5f5f5;
    margin-top: auto;
  }

  .video-card-mobile .card-actions .action-btn {
    padding: 6px 12px;
    font-size: 12px;
  }

  /* 隐藏表格，显示卡片 */
  .video-table-desktop {
    display: none !important;
  }

  /* 移动端选择工具栏 */
  .mobile-selection-bar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 10px 12px;
    background: #fff;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    margin-bottom: 8px;
  }

  .mobile-selection-bar .select-all {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 13px;
    font-weight: 500;
    color: #333;
  }

  .mobile-selection-bar .select-all input {
    width: 18px;
    height: 18px;
    cursor: pointer;
  }

  .mobile-selection-bar .selected-count {
    flex: 1;
    font-size: 12px;
    color: #666;
  }

  .mobile-selection-bar .action-btn.small {
    padding: 6px 10px;
    font-size: 11px;
  }

  .video-cards-mobile {
    display: flex !important;
    flex-direction: column;
    gap: 12px;
    padding: 0;
    margin: 0;
    width: 100%;
    box-sizing: border-box;
  }

  .video-card-mobile {
    width: 100%;
    box-sizing: border-box;
    overflow: hidden;
  }
}

/* 视频库管理样式 */
.library-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
  margin-top: 20px;
}

/* 批量导入样式 */
.import-container {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.import-config,
.scan-results,
.import-progress {
  background: white;
  border-radius: 12px;
  padding: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.import-config h4,
.scan-results h4,
.import-progress h4 {
  margin: 0 0 20px 0;
  font-size: 18px;
  color: #1a1a2e;
}

.input-group {
  display: flex;
  gap: 12px;
}

.folder-input {
  flex: 1;
  padding: 12px 16px;
  font-size: 14px;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  transition: border-color 0.3s;
}

.folder-input:focus {
  outline: none;
  border-color: #2196F3;
}

.form-hint {
  display: block;
  margin-top: 8px;
  color: #666;
  font-size: 12px;
}

.form-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin-top: 16px;
}

.form-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

.form-actions .action-btn {
  flex: 1;
  max-width: 200px;
}

.checkbox-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}

.checkbox-label input[type="checkbox"] {
  width: 18px;
  height: 18px;
  cursor: pointer;
}

.results-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.results-header h4 {
  margin: 0;
}

.results-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #f5f7fa;
  border-radius: 8px;
  margin-bottom: 16px;
}

.results-toolbar .select-all {
  font-weight: 600;
  color: #1a1a2e;
}

.results-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.selected-count {
  font-size: 14px;
  color: #2196F3;
  font-weight: 600;
}

.video-list {
  max-height: 500px;
  overflow-y: auto;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
}

.video-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid #f0f0f0;
  cursor: pointer;
  transition: background-color 0.2s;
}

.video-item:last-child {
  border-bottom: none;
}

.video-item:hover:not(.existing) {
  background-color: #f5f5f5;
}

.video-item.selected {
  background-color: #e3f2fd;
  border-left: 4px solid #2196F3;
}

.video-item.existing {
  background-color: #f5f5f5;
  opacity: 0.6;
  cursor: not-allowed;
}

.video-checkbox {
  flex-shrink: 0;
}

.video-checkbox input[type="checkbox"] {
  width: 20px;
  height: 20px;
  cursor: pointer;
}

.exists-badge {
  padding: 4px 12px;
  background-color: #9e9e9e;
  color: white;
  border-radius: 4px;
  font-size: 12px;
}

.video-info {
  flex: 1;
  min-width: 0;
}

.video-title {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a2e;
  margin-bottom: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.video-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #666;
}

.video-meta span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.import-actions {
  margin-top: 24px;
  padding-top: 24px;
  border-top: 1px solid #e0e0e0;
  text-align: center;
}

.action-btn.large {
  padding: 16px 48px;
  font-size: 16px;
  font-weight: 600;
}

.progress-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-top: 16px;
}

.stat-item {
  padding: 20px;
  border-radius: 8px;
  text-align: center;
}

.stat-item.success {
  background-color: #e8f5e9;
}

.stat-item.warning {
  background-color: #fff3e0;
}

.stat-item.error {
  background-color: #ffebee;
}

.stat-label {
  display: block;
  font-size: 14px;
  color: #666;
  margin-bottom: 8px;
}

.stat-value {
  display: block;
  font-size: 32px;
  font-weight: 700;
}

.stat-item.success .stat-value {
  color: #4caf50;
}

.stat-item.warning .stat-value {
  color: #ff9800;
}

.stat-item.error .stat-value {
  color: #f44336;
}

.import-errors {
  margin-top: 20px;
  padding: 16px;
  background-color: #ffebee;
  border-radius: 8px;
}

.import-errors h5 {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: #c62828;
}

.import-errors ul {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: #666;
}

.import-errors li {
  margin-bottom: 8px;
}

.card {
  background: white;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.required {
  color: #f44336;
}

/* 文件夹浏览器样式 */
.folder-browser-modal {
  width: 800px;
  max-width: 90vw;
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}

.folder-browser-modal .modal-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.current-path-display {
  padding: 12px 16px;
  background: #f5f5f5;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 14px;
}

.path-label {
  color: #666;
  margin-right: 8px;
}

.path-value {
  color: #1a1a2e;
  font-weight: 600;
  word-break: break-all;
}

.browser-nav {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.nav-btn {
  padding: 8px 16px;
  border: 1px solid #e0e0e0;
  background: white;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.nav-btn:hover:not(:disabled) {
  background: #f5f5f5;
  border-color: #2196F3;
}

.nav-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.folder-list-container {
  flex: 1;
  overflow-y: auto;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  min-height: 300px;
  max-height: 400px;
}

.loading-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px;
  color: #666;
}

.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #e0e0e0;
  border-top-color: #2196F3;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.folder-list {
  padding: 8px;
}

.folder-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.2s;
}

.folder-item:hover {
  background-color: #e3f2fd;
}

.folder-icon {
  font-size: 24px;
  flex-shrink: 0;
}

.folder-info {
  flex: 1;
  min-width: 0;
}

.folder-name {
  font-size: 15px;
  font-weight: 600;
  color: #1a1a2e;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.folder-type {
  font-size: 12px;
  color: #666;
  margin-top: 2px;
}

.folder-arrow {
  color: #999;
  font-size: 12px;
}

.library-card {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  overflow: hidden;
  transition: transform 0.2s, box-shadow 0.2s;
}

.library-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}

.library-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.library-card-header h4 {
  margin: 0;
  font-size: 16px;
  flex: 1;
}

/* 右上角激活/禁用按钮 */
.toggle-active-btn {
  padding: 6px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 2px solid transparent;
  white-space: nowrap;
}

.toggle-active-btn.active {
  background: #52c41a;
  color: white;
  border-color: rgba(255, 255, 255, 0.3);
}

.toggle-active-btn.active:hover {
  background: #73d13d;
  transform: scale(1.05);
}

.toggle-active-btn.inactive {
  background: #8c8c8c;
  color: white;
  border-color: rgba(255, 255, 255, 0.3);
}

.toggle-active-btn.inactive:hover {
  background: #595959;
  transform: scale(1.05);
}

.status-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
}

.status-badge.active {
  background: #52c41a;
  color: white;
}

.status-badge.inactive {
  background: #8c8c8c;
  color: white;
}

.library-card-body {
  padding: 16px;
}

.library-desc {
  color: #666;
  font-size: 14px;
  margin: 0 0 12px 0;
}

.library-stats {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
  font-size: 13px;
  color: #888;
}

.library-path {
  font-size: 12px;
  color: #999;
  word-break: break-all;
  margin: 0;
}

.library-card-actions {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  background: #f5f5f5;
  border-top: 1px solid #eee;
}

.library-card-actions .action-btn {
  flex: 1;
  padding: 6px 12px;
  font-size: 12px;
}

/* 权限配置样式 */
.modal-large {
  max-width: 800px;
}

.permission-form {
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid #eee;
}

.permission-form h4,
.permission-list h4 {
  margin: 0 0 16px 0;
  font-size: 16px;
  color: #333;
}

.form-row {
  display: flex;
  gap: 16px;
  margin-bottom: 12px;
}

.form-row .form-group {
  flex: 1;
}

.permission-list {
  margin-top: 16px;
}

/* 视频库弹窗样式 */
.library-modal {
  max-width: 520px;
}

.library-modal .modal-header h3 {
  font-size: 20px;
  color: #333;
}

.library-modal .form-group {
  margin-bottom: 20px;
}

.library-modal label {
  display: block;
  font-size: 15px;
  font-weight: 500;
  color: #333;
  margin-bottom: 8px;
}

.library-modal .required {
  color: #e74c3c;
  margin-left: 4px;
}

.library-modal input[type="text"],
.library-modal textarea {
  width: 100%;
  padding: 12px 16px;
  font-size: 15px;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  transition: all 0.3s;
  box-sizing: border-box;
}

.library-modal input[type="text"]:focus,
.library-modal textarea:focus {
  outline: none;
  border-color: #3498db;
  box-shadow: 0 0 0 3px rgba(52, 152, 219, 0.1);
}

.library-modal textarea {
  resize: vertical;
  min-height: 100px;
}

.status-toggle {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status-label {
  font-size: 14px;
  color: #666;
}

.form-tip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 12px 16px;
  background: #f8f9fa;
  border-radius: 8px;
  font-size: 14px;
  color: #666;
  margin-top: 16px;
}

.tip-icon {
  font-size: 18px;
}

.btn {
  padding: 10px 24px;
  font-size: 15px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s;
  border: none;
  font-weight: 500;
}

.btn-primary {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.btn-primary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-secondary {
  background: #f5f5f5;
  color: #666;
}

.btn-secondary:hover {
  background: #e0e0e0;
}
</style>
