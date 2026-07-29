<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import { useVideoStore } from '../stores/videoStore'
import api from '../api'
import { videoApi, libraryApi } from '../api'
import { thumbnailManageApi } from '../api'
import { serviceManageApi } from '../api'
import { resourceApi } from '../api'
import {
  formatDate,
  formatPath,
  formatFileSize,
  formatBytes,
  formatUptime,
  getUsageClass,
  getRoleClass,
  getPriorityColor,
  getPriorityLabel
} from '../utils/adminCommon'
import { useToast } from '../composables/useToast'
import { withThumbToken } from '../utils/media'
import AdminLogs from '../admin/AdminLogs.vue'
import AdminMonitor from '../admin/AdminMonitor.vue'
import AdminConfig from '../admin/AdminConfig.vue'
import AdminUsers from '../admin/AdminUsers.vue'
import AdminScripts from './admin/AdminScripts.vue'

const userStore = useUserStore()
const videoStore = useVideoStore()
const router = useRouter()
// 仅资源库管理员（非全局管理员）：只开放资源库管理，隐藏其它管理标签页
const isResourceAdminOnly = computed(() => userStore.canManageResources && !userStore.isAdmin)
const { toastMessage, showToastFlag, showToast } = useToast()

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
// 热门视频排行（点赞/收藏最多）与各资源库数量
const hotStats = ref<any>(null)
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
const resourceLibraryFilter = ref<number | ''>('')  // 当前筛选的资源库ID，空字符串表示全部
const selectedVideos = ref<string[]>([])
const editingVideo = ref<any>(null)
const editingVideoTags = ref<string>('')  // 标签输入（用 "/" 分隔）
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

// 缩略图管理
const thumbConfig = ref({
  auto_generate: false,
  max_workers: 2,
  task_interval: 3,
  auto_generate_interval: 3600
})
const thumbStats = ref<any>({
  total_videos: 0,
  total_thumbnails: 0,
  no_thumbnail_count: 0,
  thumb_service_status: 'unknown',
  thumb_service_stats: null,
  is_auto_generating: false
})
const thumbLoading = ref(false)
const thumbSaving = ref(false)
const thumbGenerating = ref(false)
const thumbConfigLoaded = ref(false)

// 服务管理
const services = ref<any[]>([])
const servicesLoading = ref(false)
const servicesInterval = ref<number | null>(null)
const serviceControlLoading = ref<string | null>(null)  // 当前正在操作的服务名

// 资源库管理
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

// 文件夹管理
const libraryFolders = ref<any[]>([])
const showFolderModal = ref(false)
const editingFolder = ref<any>(null)
const folderForm = ref({
  name: '',
  path: '',
  path_type: 'folder',
  is_default: false
})
const selectedLibraryForFolder = ref<number | null>(null)
const managingFoldersFor = ref<number | null>(null)
const browserMode = ref<'folder' | 'file'>('folder')  // browser mode for folder selection

// 获取库的文件夹列表
const fetchLibraryFolders = async (libraryId: number) => {
  try {
    const res = await api.get(`/api/admin/libraries/${libraryId}/folders`) as any
    if (res.success) {
      libraryFolders.value = res.data || []
    }
  } catch (error) {
    console.error('获取文件夹列表失败:', error)
  }
}

// 添加文件夹
const addLibraryFolder = async () => {
  if (!selectedLibraryForFolder.value) return
  if (!folderForm.value.path.trim()) {
    showToast('请先选择文件夹')
    return
  }
  try {
    const res = await api.post(`/api/admin/libraries/${selectedLibraryForFolder.value}/folders`, folderForm.value) as any
    if (res.success) {
      showToast('文件夹添加成功')
      showFolderModal.value = false
      folderForm.value = { name: '', path: '', path_type: 'folder', is_default: false }
      fetchLibraryFolders(selectedLibraryForFolder.value)
    } else {
      showToast(res.message || '添加失败')
    }
  } catch (error) {
    console.error('添加文件夹失败:', error)
  }
}

// 删除文件夹
const deleteLibraryFolder = async (folderId: number) => {
  if (!confirm('确定要删除该文件夹吗？')) return
  try {
    const res = await api.delete(`/api/admin/folders/${folderId}`) as any
    if (res.success) {
      showToast('文件夹已删除')
      if (managingFoldersFor.value) {
        fetchLibraryFolders(managingFoldersFor.value)
      }
    } else {
      showToast(res.message || '删除失败')
    }
  } catch (error) {
    console.error('删除文件夹失败:', error)
  }
}

// 设置默认上传路径
const setAsDefaultFolder = async (folderId: number) => {
  try {
    const res = await api.post(`/api/admin/folders/${folderId}/set-default`) as any
    if (res.success) {
      showToast('已设为默认上传路径')
      if (managingFoldersFor.value) {
        fetchLibraryFolders(managingFoldersFor.value)
      }
    } else {
      showToast(res.message || '设置失败')
    }
  } catch (error) {
    console.error('设置默认路径失败:', error)
  }
}

// 打开文件夹管理
const manageFolders = (lib: any) => {
  managingFoldersFor.value = lib.id
  selectedLibraryForFolder.value = lib.id
  fetchLibraryFolders(lib.id)
  showFolderModal.value = true
}


// ============ 资源库详情展开视图（在"资源库管理"标签页中使用） ============
const expandedLibraryId = ref<number | null>(null)
const libraryDetailFolders = ref<any[]>([])
const libraryDetailFolderKey = ref('__all__')       // '__all__' = 所有文件夹
const libraryDetailFileCache = ref<Record<string, any[]>>({})
const libraryDetailScanning = ref(false)
const libraryDetailSelectedFiles = ref<string[]>([])
const libraryDetailImporting = ref(false)
const libraryDetailImportProgress = ref({ imported: 0, skipped: 0, failed: 0 })
const libraryDetailImportErrors = ref<string[]>([])
// 扫描进度反馈（正在扫描哪个文件夹、已发现几个）
const libraryDetailScanInfo = ref<{ folder: string; index: number; total: number; found: number } | null>(null)
// 扫描完成后的汇总（共多少、多少新、多少已存在）
const libraryDetailScanSummary = ref<{ total: number; newCount: number; existCount: number } | null>(null)
// 扫描过程中各文件夹的失败原因（如路径不存在/无权限），用于向用户解释为什么是 0
const libraryDetailScanErrors = ref<{ folder: string; message: string }[]>([])

// 当前展开的资源库对象
const currentLibrary = computed(() => {
  return libraries.value.find(l => l.id === expandedLibraryId.value) || null
})

// 当前文件夹下待展示的文件列表
const libraryDetailCurrentFiles = computed(() => {
  return libraryDetailFileCache.value[libraryDetailFolderKey.value] || []
})

// 展开资源库详情
const enterLibraryDetail = async (lib: any) => {
  expandedLibraryId.value = lib.id

  // 切换资源库时清空上一库的扫描缓存与状态，避免串库显示旧数据
  libraryDetailFileCache.value = {}
  libraryDetailSelectedFiles.value = []
  libraryDetailScanSummary.value = null
  libraryDetailScanInfo.value = null
  libraryDetailImporting.value = false
  libraryDetailScanning.value = false

  // 获取关联文件夹
  try {
    const res = await api.get(`/api/admin/libraries/${lib.id}/folders`) as any
    if (res.success && res.data) {
      libraryDetailFolders.value = res.data
    } else {
      libraryDetailFolders.value = []
    }
  } catch (e) {
    console.error('获取文件夹列表失败:', e)
    libraryDetailFolders.value = []
  }

  libraryDetailFolderKey.value = '__all__'
}

// 收起资源库详情
const leaveLibraryDetail = () => {
  expandedLibraryId.value = null
  libraryDetailFileCache.value = {}
  libraryDetailSelectedFiles.value = []
  libraryDetailImporting.value = false
}

// 扫描文件夹
const scanDetailFolder = async (folderKey?: string) => {
  const lib = currentLibrary.value
  if (!lib) return

  const key = folderKey || libraryDetailFolderKey.value
  libraryDetailScanning.value = true
  libraryDetailScanInfo.value = null
  libraryDetailScanSummary.value = null
  libraryDetailScanErrors.value = []

  try {
    const foldersToScan = key === '__all__'
      ? libraryDetailFolders.value
      : libraryDetailFolders.value.filter((f: any) => getFolderKey(f) === key)

    if (foldersToScan.length === 0) {
      showToast('没有可扫描的文件夹')
      libraryDetailScanning.value = false
      return
    }

    const seenPaths = new Set<string>()
    const allResults: any[] = []
    const folderResults: Record<string, any[]> = {}
    let scannedCount = 0

    for (let i = 0; i < foldersToScan.length; i++) {
      const folder = foldersToScan[i]
      const folderPath = folder.path
      if (!folderPath || !folderPath.trim()) continue
      scannedCount++
      // 实时反馈当前正在扫描的文件夹与已发现数量，避免用户误以为卡死
      libraryDetailScanInfo.value = {
        folder: getFolderLabel(folder),
        index: scannedCount,
        total: foldersToScan.length,
        found: allResults.length
      }

      try {
        const scanRes = await api.post('/api/admin/scan-folder', {
          folder_path: folderPath,
          recursive: true
        }, { timeout: 900000 }) as any

        if (scanRes.success && scanRes.data?.videos) {
          const fKey = getFolderKey(folder)
          if (!folderResults[fKey]) folderResults[fKey] = []

          for (const v of scanRes.data.videos) {
            if (!seenPaths.has(v.path)) {
              seenPaths.add(v.path)
              allResults.push(v)
              folderResults[fKey].push(v)
            }
          }
        } else if (scanRes && scanRes.success === false) {
          // 后端明确返回失败（如文件夹不存在/无权限），记录下来告知用户
          libraryDetailScanErrors.value.push({
            folder: getFolderLabel(folder),
            message: scanRes.message || '扫描失败'
          })
        }
      } catch (e: any) {
        console.error(`扫描文件夹失败: ${folderPath}`, e)
        libraryDetailScanErrors.value.push({
          folder: getFolderLabel(folder),
          message: e?.response?.data?.message || e?.message || '请求失败'
        })
      }
    }

    // 更新各文件夹缓存
    for (const [fKey, videos] of Object.entries(folderResults)) {
      libraryDetailFileCache.value[fKey] = videos
    }
    libraryDetailFileCache.value['__all__'] = allResults

    const newCount = allResults.filter((v: any) => !v.exists).length
    const existCount = allResults.filter((v: any) => v.exists).length

    // 记录汇总，并在扫描结果区展示，便于一键导入
    libraryDetailScanSummary.value = { total: allResults.length, newCount, existCount }
    // 默认全选所有新视频，省去手动勾选这一步
    libraryDetailSelectedFiles.value = allResults.filter((v: any) => !v.exists).map((v: any) => v.path)

    if (allResults.length === 0) {
      if (libraryDetailScanErrors.value.length > 0) {
        const msgs = libraryDetailScanErrors.value.map((e) => `${e.folder}：${e.message}`).join('；')
        showToast(`扫描完成但 0 个视频，${libraryDetailScanErrors.value.length} 个文件夹访问失败：${msgs}`)
      } else {
        showToast('扫描完成：未发现视频文件')
      }
    } else {
      showToast(`扫描完成：共 ${allResults.length} 个视频（${newCount} 个新视频，${existCount} 个已存在）`)
    }
  } catch (error: any) {
    console.error('扫描失败:', error)
    showToast(error.response?.data?.message || error.message || '扫描失败')
  } finally {
    libraryDetailScanning.value = false
    libraryDetailScanInfo.value = null
  }
}

// 一键扫描全部资源库（自动对齐文件名/标题，覆盖软件未运行或旧逻辑漏更新的情况）
const scanAllScanning = ref(false)
const scanAllMessage = ref('')
let scanAllTimer: any = null

const scanAllLibraries = async () => {
  try {
    const res = await libraryApi.scanAllLibraries() as any
    if (res.success) {
      scanAllScanning.value = true
      scanAllMessage.value = '全量扫描已启动...'
      pollScanAll()
    } else {
      showToast(res.message || '启动失败')
    }
  } catch (e: any) {
    console.error('启动全量扫描失败:', e)
    showToast(e?.response?.data?.message || e?.message || '启动失败')
  }
}

const pollScanAll = () => {
  if (scanAllTimer) clearInterval(scanAllTimer)
  scanAllTimer = setInterval(async () => {
    try {
      const res = await libraryApi.getScanAllStatus() as any
      if (res.success) {
        scanAllMessage.value = res.message || ''
        if (res.status === 'done' || res.status === 'error') {
          scanAllScanning.value = false
          if (scanAllTimer) { clearInterval(scanAllTimer); scanAllTimer = null }
          showToast(res.message || '扫描完成')
        }
      }
    } catch (e) {
      if (scanAllTimer) { clearInterval(scanAllTimer); scanAllTimer = null }
      scanAllScanning.value = false
    }
  }, 1500)
}

// 文件夹唯一Key
const getFolderKey = (folder: any) => {
  return folder.path || `folder_${folder.id}`
}

// 文件夹显示名（取最后一级目录名）
const getFolderLabel = (folder: any) => {
  if (folder.name) return folder.name
  const path = folder.path || ''
  const parts = path.replace(/\\/g, '/').split('/').filter(Boolean)
  return parts[parts.length - 1] || path || '(未知)'
}

// 全选/取消全选
const detailToggleSelectAll = () => {
  const files = libraryDetailCurrentFiles.value.filter((v: any) => !v.exists)
  if (libraryDetailSelectedFiles.value.length === files.length) {
    libraryDetailSelectedFiles.value = []
  } else {
    libraryDetailSelectedFiles.value = files.map((v: any) => v.path)
  }
}

// 切换单个文件选择
const detailToggleFile = (path: string) => {
  const idx = libraryDetailSelectedFiles.value.indexOf(path)
  if (idx > -1) {
    libraryDetailSelectedFiles.value.splice(idx, 1)
  } else {
    libraryDetailSelectedFiles.value.push(path)
  }
}

// 导入选中视频
const detailImportVideos = async () => {
  const lib = currentLibrary.value
  if (!lib) return
  if (libraryDetailSelectedFiles.value.length === 0) {
    showToast('请选择要导入的视频')
    return
  }

  libraryDetailImporting.value = true
  libraryDetailImportProgress.value = { imported: 0, skipped: 0, failed: 0 }
  libraryDetailImportErrors.value = []

  try {
    const currentFiles = libraryDetailCurrentFiles.value
    const videosToImport = currentFiles
      .filter((v: any) => libraryDetailSelectedFiles.value.includes(v.path))
      .map((v: any) => ({ path: v.path, title: v.title, tags: [] as string[] }))

    const res = await api.post('/api/admin/import-videos', {
      library_id: lib.id,
      videos: videosToImport,
      skip_existing: true,
      default_tags: []
    }, { timeout: 900000 }) as any

    if (res.success) {
      libraryDetailImportProgress.value = res.data
      libraryDetailImportErrors.value = res.data.errors || []
      showToast(res.message)
      await fetchVideos()

      // 更新缓存：标记已导入的视频为"已存在"
      const importedPaths = new Set(videosToImport.map((v: any) => v.path))
      for (const key of Object.keys(libraryDetailFileCache.value)) {
        libraryDetailFileCache.value[key] = libraryDetailFileCache.value[key].map((v: any) => ({
          ...v,
          exists: v.exists || importedPaths.has(v.path)
        }))
      }
      // 导入完成后刷新汇总：新视频已全部导入
      if (libraryDetailScanSummary.value) {
        libraryDetailScanSummary.value = {
          total: libraryDetailScanSummary.value.total,
          newCount: 0,
          existCount: libraryDetailScanSummary.value.total
        }
      }
      libraryDetailSelectedFiles.value = []
    } else {
      showToast(res.message || '导入失败')
    }
  } catch (error: any) {
    console.error('导入失败:', error)
    showToast(error.response?.data?.message || error.message || '导入失败')
  } finally {
    libraryDetailImporting.value = false
  }
}

// 用户组
const userGroups = ref<any[]>([])


// 文件夹浏览器
const showFolderBrowser = ref(false)
const browserPath = ref('')
const browserFolders = ref<any[]>([])
const browserLoading = ref(false)
const browserError = ref('')
const browserHistory = ref<string[]>([])

// 权限级别选项
const accessLevelOptions = [
  { value: 'full', label: '完全访问' },
  { value: 'write', label: '可读写' },
  { value: 'read', label: '只读' },
  { value: 'custom', label: '自定义' }
]

// 获取当前用户可管理的资源库（全局管理员返回全部；资源库管理员返回其管理的库）
const fetchLibraries = async () => {
  loading.value.libraries = true
  try {
    const res = await api.get('/api/my-libraries') as any
    if (res.success) {
      libraries.value = res.data
    }
  } catch (error) {
    console.error('获取资源库列表失败:', error)
  } finally {
    loading.value.libraries = false
  }
}

// ============ 资源管理（视频/图集/帖子/文本 统一列表，管理员高权限） ============
const resources = ref<any[]>([])
const resourceSearch = ref('')
const resourceTypeFilter = ref('')
const resourcePage = ref(1)
const resourceTotal = ref(0)
const resourceLoading = ref(false)
// 是否显示已隐藏的资源（隐藏属性位于公共层 resource_index.hidden）
const showHiddenResources = ref(true)
const editingResource = ref<any>(null)
const showResourceEditModal = ref(false)
const RESOURCE_PAGE_SIZE = 20

const libraryName = (libId: any) => {
  if (libId === null || libId === undefined || libId === '') return '-'
  const lib = libraries.value.find((l: any) => l.id === Number(libId))
  return lib ? lib.name : `#${libId}`
}
const resourceTypeLabel = (t: string) => ({ video: '视频', gallery: '图集', post: '帖子', text: '文本' }[t] || t)

const formatDuration = (sec: any) => {
  if (sec === null || sec === undefined || isNaN(Number(sec))) return '-'
  const s = Math.round(Number(sec))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(ss)}` : `${m}:${pad(ss)}`
}
const formatResolution = (w: any, h: any) => {
  if (!w || !h) return '-'
  return `${w}×${h}`
}
const formatCount = (n: any) => (n === null || n === undefined ? '-' : String(n))

// 资源类型图标（用于资源管理列表的行首标识）
const typeIcon = (t: string) => {
  switch (t) {
    case 'video': return '🎬'
    case 'gallery': return '🖼️'
    case 'post': return '📝'
    case 'text': return '📄'
    default: return '📦'
  }
}
const typeLabel = (t: string) => {
  switch (t) {
    case 'video': return '视频'
    case 'gallery': return '图集'
    case 'post': return '帖子'
    case 'text': return '文本'
    default: return '资源'
  }
}

// 空状态行的跨列数：随当前子标签动态计算（类型 + 标题 + 各类型独有列 + 资源库 + 更新时间 + 操作）
const resourceColspan = computed(() => {
  let base = 1 + 1 + 1 + 1 + 1 // 类型 + 标题 + 资源库 + 更新时间 + 操作
  if (resourceTypeFilter.value === '' || resourceTypeFilter.value === 'video') base += 3 // 大小+时长+分辨率
  if (resourceTypeFilter.value === 'gallery') base += 1 // 图片个数
  if (resourceTypeFilter.value === 'post') base += 1 // 正文字数
  if (resourceTypeFilter.value === 'text') base += 1 // 字数
  return base
})

const fetchResources = async (resetPage = true) => {
  if (resetPage) resourcePage.value = 1
  resourceLoading.value = true
  try {
    const params: any = { limit: RESOURCE_PAGE_SIZE, offset: (resourcePage.value - 1) * RESOURCE_PAGE_SIZE }
    if (resourceSearch.value.trim()) params.search = resourceSearch.value.trim()
    if (resourceTypeFilter.value) params.type = resourceTypeFilter.value
    if (resourceLibraryFilter.value !== '') params.library_id = resourceLibraryFilter.value
    params.show_hidden = showHiddenResources.value ? 'true' : 'false'
    const res = await api.get('/api/admin/resources', { params }) as any
    if (res.success) {
      resources.value = res.items || []
      resourceTotal.value = res.total || 0
    }
  } catch (e) {
    console.error('加载资源列表失败:', e)
  } finally {
    resourceLoading.value = false
  }
}

const editResource = (item: any) => {
  // 帖子/文本需先拉取完整内容用于编辑
  const r = { ...item }
  if (item.type === 'post' || item.type === 'text') {
    api.get(`/api/${item.type === 'post' ? 'posts' : 'texts'}/${item.id}`)
      .then((res: any) => {
        const full = res.data || res
        r.content = full.content || ''
        r.summary = full.summary || ''
        r.body = full.body || ''
        editingResource.value = r
        showResourceEditModal.value = true
      })
      .catch(() => { editingResource.value = r; showResourceEditModal.value = true })
  } else {
    editingResource.value = r
    showResourceEditModal.value = true
  }
}

const saveResourceEdit = async () => {
  const r = editingResource.value
  if (!r) return
  try {
    const payload: any = { title: r.title }
    if (r.type === 'post') payload.content = r.content
    if (r.type === 'text') { payload.summary = r.summary; payload.body = r.body }
    const res = await api.put(`/api/admin/resources/${r.type}/${r.id}`, payload) as any
    if (res.success) {
      showToast('保存成功')
      showResourceEditModal.value = false
      fetchResources(false)
    } else {
      showToast(res.message || '保存失败')
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || e?.message || '保存失败')
  }
}

const deleteResource = async (item: any) => {
  if (!confirm(`确定删除该${resourceTypeLabel(item.type)}「${item.title}」？此操作不可恢复。`)) return
  try {
    const res = await api.delete(`/api/admin/resources/${item.type}/${item.id}`) as any
    if (res.success) {
      showToast('删除成功')
      fetchResources(false)
    } else {
      showToast(res.message || '删除失败')
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || e?.message || '删除失败')
  }
}

// 切换资源显示/隐藏（公共层：resource_index.hidden）
const togglingHidden = ref<number | null>(null) // 正在切换的资源索引 id
const toggleResourceHidden = async (item: any) => {
  const rid = item.resource_index_id
  if (!rid) {
    showToast('该资源未关联资源索引，无法切换显示状态')
    return
  }
  togglingHidden.value = rid
  try {
    const res: any = await resourceApi.setHidden(rid, !item.hidden) as any
    if (res && res.success) {
      const updated = res.hidden
      item.hidden = updated
      showToast(updated ? '已隐藏' : '已显示')
    } else {
      showToast((res && res.message) || '操作失败')
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || e?.message || '操作失败')
  } finally {
    togglingHidden.value = null
  }
}

// 创建资源库
const createLibrary = async () => {
  if (!libraryForm.value.name.trim()) {
    showToast('请输入资源库名称')
    return
  }
  try {
    creatingLibrary.value = true
    const res = await api.post('/api/admin/libraries', libraryForm.value) as any
    if (res.success) {
      showToast('资源库创建成功')
      showLibraryModal.value = false
      libraryForm.value = { name: '', description: '', db_file: '', config: {} }
      fetchLibraries()
    } else {
      showToast(res.message || '创建失败')
    }
  } catch (error: any) {
    console.error('创建资源库失败:', error)
    showToast(error.response?.data?.message || '创建失败')
  } finally {
    creatingLibrary.value = false
  }
}

// 更新资源库
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
    console.error('更新资源库失败:', error)
    showToast('更新失败')
  }
}

// 删除资源库
const deleteLibrary = async (id: number) => {
  if (!confirm('确定要删除该资源库吗？')) return
  try {
    const res = await api.delete(`/api/admin/libraries/${id}`) as any
    if (res.success) {
      showToast('删除成功')
      fetchLibraries()
    }
  } catch (error) {
    console.error('删除资源库失败:', error)
    showToast('删除失败')
  }
}

// 切换资源库激活状态
const toggleLibraryActive = async (lib: any) => {
  try {
    const newStatus = !lib.is_active
    const res = await api.put(`/api/admin/libraries/${lib.id}`, {
      ...lib,
      is_active: newStatus
    }) as any
    if (res.success) {
      showToast(newStatus ? '资源库已激活' : '资源库已禁用')
      fetchLibraries()
    }
  } catch (error) {
    console.error('切换资源库状态失败:', error)
    showToast('操作失败')
  }
}

// 编辑资源库
const editLibrary = (lib: any) => {
  editingLibrary.value = { ...lib }
  showLibraryModal.value = true
}

// 获取资源库权限
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

// ============ 文件夹浏览器功能 ============


// 打开文件夹浏览器（用于向当前资源库导入：选择其他文件夹）
// 文件夹浏览器用途：import=导入其他文件夹（选择后触发扫描），addFolder=给资源库添加扫描路径
const browserPurpose = ref<'import' | 'addFolder'>('import')
const newFolderName = ref('')

// 浏览服务器文件系统：读取指定路径下的子目录（及可选文件）
const loadFolderList = async (path: string, isFile: boolean = false) => {
  browserLoading.value = true
  browserError.value = ''
  try {
    const params: any = { path: path || '' }
    if (isFile) params.files = '1'
    const res = await api.get('/api/admin/system/folders', { params }) as any
    if (res && res.success) {
      browserFolders.value = res.folders || []
      if (isFile) browserFolders.value = [...browserFolders.value, ...(res.files || [])]
    } else {
      browserError.value = (res && res.message) || '加载失败'
    }
  } catch (e: any) {
    browserError.value = (e && e.message) || '加载失败'
  } finally {
    browserLoading.value = false
  }
}

// 进入子文件夹 / 盘符
const enterFolder = (item: any) => {
  if (!item || (item.type !== 'folder' && item.type !== 'drive')) return
  browserHistory.value = [...browserHistory.value, browserPath.value]
  browserPath.value = item.path
  loadFolderList(item.path, browserMode.value === 'file')
}

// 返回上级
const goBack = () => {
  if (browserHistory.value.length === 0) {
    browserPath.value = ''
    loadFolderList('', browserMode.value === 'file')
    return
  }
  const prev = browserHistory.value[browserHistory.value.length - 1]
  browserHistory.value = browserHistory.value.slice(0, -1)
  browserPath.value = prev
  loadFolderList(prev, browserMode.value === 'file')
}

// 在当前路径下新建文件夹
const createFolderInBrowser = async () => {
  const name = (newFolderName.value || '').trim()
  if (!name) {
    showToast('请输入文件夹名称')
    return
  }
  try {
    const res = await api.post('/api/admin/system/folders', {
      path: browserPath.value || '',
      name
    }) as any
    if (res && res.success) {
      showToast('文件夹已创建')
      newFolderName.value = ''
      await loadFolderList(browserPath.value, browserMode.value === 'file')
    } else {
      showToast((res && res.message) || '创建失败')
    }
  } catch (e: any) {
    showToast((e && e.message) || '创建失败')
  }
}

// 打开文件夹浏览器（用于向当前资源库导入：选择其他文件夹）
const openLibraryImportFolderBrowser = async () => {
  if (expandedLibraryId.value == null) return
  browserPurpose.value = 'import'
  showFolderBrowser.value = true
  browserPath.value = ''
  browserHistory.value = []
  browserMode.value = 'folder'
  newFolderName.value = ''
  await loadFolderList('', false)
}

// 打开文件夹浏览器（用于给资源库添加扫描路径）
const openFolderBrowserForAdd = async () => {
  if (selectedLibraryForFolder.value == null) return
  browserPurpose.value = 'addFolder'
  showFolderBrowser.value = true
  browserPath.value = ''
  browserHistory.value = []
  browserMode.value = 'folder'
  newFolderName.value = ''
  await loadFolderList('', false)
}

// 弹窗打开时锁定背景滚动，避免滑动弹窗时触发背后界面滚动
let _bodyLockObserver: MutationObserver | null = null
onMounted(() => {
  _bodyLockObserver = new MutationObserver(() => {
    const hasOverlay = !!document.querySelector('.modal-overlay, .dialog-overlay')
    document.body.style.overflow = hasOverlay ? 'hidden' : ''
  })
  _bodyLockObserver.observe(document.body, { childList: true, subtree: true })
})
onUnmounted(() => {
  if (_bodyLockObserver) {
    _bodyLockObserver.disconnect()
    _bodyLockObserver = null
  }
  document.body.style.overflow = ''
})

// 选择文件夹后：作为“其他文件夹”扫描并导入到当前资源库
const selectCurrentFolder = () => {
  const p = browserPath.value
  showFolderBrowser.value = false
  if (!p || expandedLibraryId.value == null) return
  const synth = { path: p, name: getFolderLabel({ path: p }) }
  if (!libraryDetailFolders.value.some((f: any) => f.path === p)) {
    libraryDetailFolders.value = [...libraryDetailFolders.value, synth]
  }
  libraryDetailFolderKey.value = p
  scanDetailFolder(p)
}

// 从浏览器选择路径（用于添加库文件夹）
const selectPathFromBrowser = () => {
  if (!browserPath.value) return
  // 自动从路径提取名称
  const parts = browserPath.value.replace(/\\/g, '/').split('/')
  const folderName = parts[parts.length - 1] || parts[parts.length - 2] || '未命名'
  folderForm.value.name = folderName
  folderForm.value.path = browserPath.value
  // 根据是否在浏览文件模式决定类型（实际上路径本身就能判断）
  folderForm.value.path_type = 'folder'
  showFolderBrowser.value = false
}

// 从浏览器选择文件（用于添加库文件夹 - 直接点击文件时）
const selectFileFromBrowser = (item: any) => {
  // 自动从文件名提取名称
  const fileName = item.name || item.display || '未命名'
  const nameWithoutExt = fileName.replace(/\.[^/.]+$/, '')  // 去掉扩展名
  folderForm.value.name = nameWithoutExt
  folderForm.value.path = item.path
  folderForm.value.path_type = 'file'
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

// 获取热门视频排行与资源库分布
const loadHotStats = async () => {
  try {
    const r = await videoApi.getStats() as any
    if (r && r.success) hotStats.value = r
  } catch (e) {
    console.error('获取热门统计失败:', e)
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
    if (resourceLibraryFilter.value !== '') params.library_id = resourceLibraryFilter.value
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

// ============ 缩略图管理 ============

const fetchThumbnailConfig = async () => {
  thumbLoading.value = true
  try {
    const res = await thumbnailManageApi.getConfig() as any
    if (res.success) {
      thumbConfig.value = { ...thumbConfig.value, ...res.config }
      thumbStats.value = res.stats
      thumbConfigLoaded.value = true
    }
  } catch (error) {
    console.error('获取缩略图配置失败:', error)
  } finally {
    thumbLoading.value = false
  }
}

const saveThumbnailConfig = async () => {
  thumbSaving.value = true
  try {
    const res = await thumbnailManageApi.updateConfig(thumbConfig.value) as any
    if (res.success) {
      showToast('缩略图配置已保存')
      // 刷新统计
      fetchThumbnailConfig()
    } else {
      showToast(res.message || '保存失败')
    }
  } catch (error) {
    console.error('保存缩略图配置失败:', error)
    showToast('保存失败')
  } finally {
    thumbSaving.value = false
  }
}

const triggerGenerateMissing = async () => {
  thumbGenerating.value = true
  try {
    const res = await thumbnailManageApi.generateMissing() as any
    if (res.success) {
      showToast(`已提交 ${res.submitted} 个缩略图生成任务`)
      // 延迟刷新统计
      setTimeout(() => fetchThumbnailConfig(), 5000)
    } else {
      showToast(res.message || '生成失败')
    }
  } catch (error) {
    console.error('触发生成失败:', error)
    showToast('触发失败')
  } finally {
    thumbGenerating.value = false
  }
}

const stopAutoGenerate = async () => {
  try {
    const res = await thumbnailManageApi.stopAuto() as any
    if (res.success) {
      showToast(res.message || '自动生成已停止')
      thumbConfig.value.auto_generate = false
      thumbStats.value.is_auto_generating = false
    }
  } catch (error) {
    console.error('停止自动生成失败:', error)
    showToast('停止失败')
  }
}

// 缩略图自动生成间隔格式化
const formatInterval = (seconds: number) => {
  if (seconds < 60) return `${seconds} 秒`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} 分钟`
  return `${(seconds / 3600).toFixed(1)} 小时`
}

// 缩略图服务状态文本
const thumbServiceStatusText = (status: string) => {
  const map: Record<string, string> = {
    running: '运行中',
    offline: '离线',
    error: '异常',
    unknown: '未知'
  }
  return map[status] || status
}

// 缩略图服务状态颜色
const thumbServiceStatusClass = (status: string) => {
  const map: Record<string, string> = {
    running: 'status-ok',
    offline: 'status-error',
    error: 'status-error',
    unknown: 'status-unknown'
  }
  return map[status] || ''
}

// ============ 服务管理 ============

const fetchServices = async () => {
  servicesLoading.value = true
  try {
    const res = await serviceManageApi.getServices() as any
    if (res.success) {
      services.value = res.services
    }
  } catch (error) {
    console.error('获取服务列表失败:', error)
  } finally {
    servicesLoading.value = false
  }
}

// 启动/停止/重启轮询
const startServicePolling = (fast = false) => {
  stopServicePolling()
  const interval = fast ? 2000 : 10000  // 正常10秒，加速2秒
  servicesInterval.value = window.setInterval(() => {
    fetchServices()
  }, interval)
}

const stopServicePolling = () => {
  if (servicesInterval.value) {
    clearInterval(servicesInterval.value)
    servicesInterval.value = null
  }
}

const controlService = async (serviceName: string, action: 'start' | 'stop' | 'restart') => {
  serviceControlLoading.value = serviceName
  try {
    const res = await serviceManageApi.control(serviceName, action) as any
    if (res.success) {
      const actionText: Record<string, string> = {
        start: '启动',
        stop: '停止',
        restart: '重启',
      }
      showToast(`${actionText[action]}成功`)

      // 重启中：加速轮询直到服务恢复运行
      if (action === 'restart' || action === 'start') {
        startServicePolling(true)
        // 15次加速轮询后恢复正常频率
        let count = 0
        const checkInterval = setInterval(async () => {
          count++
          try {
            const statusRes = await serviceManageApi.getServices() as any
            if (statusRes.success) {
              const svc = statusRes.services.find((s: any) => s.service_name === serviceName)
              if (svc && svc.system_status === 'RUNNING') {
                clearInterval(checkInterval)
                startServicePolling(false)
              }
            }
          } catch {}
          if (count >= 15) {
            clearInterval(checkInterval)
            startServicePolling(false)
          }
        }, 2000)
      } else {
        // 停止后刷新一次
        setTimeout(() => fetchServices(), 1000)
      }
    } else {
      showToast(res.message || '操作失败')
    }
  } catch (error: any) {
    console.error('控制服务失败:', error)
    showToast(error.response?.data?.message || '操作失败')
  } finally {
    serviceControlLoading.value = null
  }
}

// 服务状态显示文本
const systemStatusText = (status: string) => {
  const map: Record<string, string> = {
    RUNNING: '运行中',
    STOPPED: '已停止',
    START_PENDING: '启动中',
    STOP_PENDING: '停止中',
    PAUSE_PENDING: '暂停中',
    PAUSED: '已暂停',
    CONTINUE_PENDING: '恢复中',
    unknown: '未知',
  }
  return map[status] || status
}

const systemStatusClass = (status: string) => {
  if (status === 'RUNNING') return 'svc-running'
  if (status === 'PAUSED') return 'svc-paused'
  if (status === 'STOPPED') return 'svc-stopped'
  if (status.includes('PENDING')) return 'svc-pending'
  return 'svc-unknown'
}

const healthStatusClass = (status: string) => {
  if (status === 'healthy') return 'svc-running'
  if (status === 'unhealthy') return 'svc-stopped'
  return 'svc-unknown'
}

const healthStatusIcon = (status: string) => {
  if (status === 'healthy') return '🟢'
  if (status === 'unhealthy') return '🔴'
  return '⚪'
}

// 判断按钮是否可用
const canStart = (svc: any) => {
  const s = svc.system_status
  return s === 'STOPPED' || s === 'PAUSED'
}

const canStop = (svc: any) => {
  return svc.system_status === 'RUNNING'
}

const canRestart = (svc: any) => {
  return svc.system_status === 'RUNNING'
}

const isOperating = (serviceName: string) => {
  const s = serviceControlLoading.value === serviceName
  const svc = services.value.find(sv => sv.service_name === serviceName)
  // 操作中：显式 loading 或状态处于 PENDING
  const pending = svc && svc.system_status.includes('PENDING')
  return s || pending
}

// 编辑视频
const editVideo = async (video: any) => {
  editingVideo.value = { ...video }
  // 加载当前视频的标签
  try {
    const res = await api.get(`/api/video/${video.hash}`) as any
    if (res.success && res.video && res.video.tags) {
      // 将标签对象数组转换为路径字符串
      editingVideoTags.value = res.video.tags.map((t: any) => t.path || t.name).join(' / ')
    } else {
      editingVideoTags.value = ''
    }
  } catch (e) {
    editingVideoTags.value = ''
  }
  showVideoEditModal.value = true
}

// 保存视频编辑
const saveVideoEdit = async () => {
  if (!editingVideo.value) return
  try {
    // 先保存基本信息
    const res = await api.post(`/api/videos/${editingVideo.value.hash}/update`, {
      title: editingVideo.value.title,
      description: editingVideo.value.description,
      priority: editingVideo.value.priority
    }) as any
    
    if (res.success) {
      // 再保存标签
      const tagPaths = editingVideoTags.value
        .split('/')
        .map((t: string) => t.trim())
        .filter((t: string) => t)
      
      await api.post(`/api/video/${editingVideo.value.hash}/tags`, {
        tags: tagPaths
      })
      
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

// 全选/取消全选
const toggleSelectAll = () => {
  if (selectedVideos.value.length === videos.value.length) {
    selectedVideos.value = []
  } else {
    selectedVideos.value = videos.value.map(v => v.hash)
  }
}

// ============ 回收站 ============
const trashItems = ref<any[]>([])
const trashLoading = ref(false)

const loadTrash = async () => {
  trashLoading.value = true
  try {
    const res = await api.getTrash()
    if (res.data.success) {
      trashItems.value = res.data.items || []
    } else {
      ElMessage.error(res.data.message || '加载回收站失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '加载回收站失败')
  } finally {
    trashLoading.value = false
  }
}

const restoreTrashItem = async (item: any) => {
  try {
    const res = await api.restoreTrash(item.type, item.hash)
    if (res.data.success) {
      ElMessage.success('已恢复')
      loadTrash()
    } else {
      ElMessage.error(res.data.message || '恢复失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '恢复失败')
  }
}

const purgeTrashItem = async (item: any) => {
  if (!window.confirm(`确定要永久删除「${item.title}」吗？此操作不可恢复。`)) return
  try {
    const res = await api.purgeTrash(item.type, item.hash)
    if (res.data.success) {
      ElMessage.success('已永久删除')
      loadTrash()
    } else {
      ElMessage.error(res.data.message || '删除失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '删除失败')
  }
}

const emptyTrash = async () => {
  if (trashItems.value.length === 0) return
  if (!window.confirm('确定要清空回收站吗？所有资源将被永久删除，不可恢复。')) return
  try {
    const res = await api.emptyTrash()
    if (res.data.success) {
      ElMessage.success(res.data.message || '已清空回收站')
      loadTrash()
    } else {
      ElMessage.error(res.data.message || '清空失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '清空失败')
  }
}

const formatTrashTime = (iso: string | null) => {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

const formatSize = (bytes: number) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
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

// ============ 切换标签页 ============
const switchTab = (tab: string) => {
  activeTab.value = tab
  if (tab === 'trash') { loadTrash() }
  if (tab === 'thumbnail') fetchThumbnailConfig()
  if (tab === 'services') { fetchServices(); startServicePolling() }
  if (tab === 'libraries') {
    fetchLibraries()
    fetchUserGroups()
  }
  if (tab === 'resources') { fetchLibraries(); fetchResources() }
  // 离开服务管理页时停止轮询
  if (tab !== 'services') stopServicePolling()
}

onMounted(() => {
  fetchSystemInfo()
  fetchSystemStats()
  fetchSystemPaths()
  fetchSyncStatus()
  loadHotStats()
  // 恢复上次的标签页数据（日志/监控/用户/配置由各子组件自行加载）
  const restoredTab = activeTab.value
  if (restoredTab === 'thumbnail') fetchThumbnailConfig()
  else if (restoredTab === 'services') { fetchServices(); startServicePolling() }
  else if (restoredTab === 'libraries') { fetchLibraries(); if (userStore.isAdmin) fetchUserGroups() }
  else if (restoredTab === 'resources') { fetchLibraries(); fetchResources() }
})

// 组件卸载时停止轮询
onUnmounted(() => {
  stopServicePolling()
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

    <!-- 标签页导航（按职责分组，避免平铺混乱） -->
    <div class="admin-tabs">
      <div class="tab-group">
        <span class="tab-group-label">内容</span>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'dashboard' }"
          @click="switchTab('dashboard')"
          v-if="!isResourceAdminOnly"
        >📊 仪表板</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'resources' }"
          @click="switchTab('resources')"
          v-if="!isResourceAdminOnly"
        >🗂️ 资源管理</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'trash' }"
          @click="switchTab('trash')"
          v-if="userStore.isAdmin"
        >🗑️ 回收站</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'libraries' }"
          @click="switchTab('libraries')"
          v-if="userStore.isRoot || userStore.canManageResources"
        >📁 资源库管理</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'thumbnail' }"
          @click="switchTab('thumbnail')"
          v-if="!isResourceAdminOnly"
        >🖼️ 缩略图管理</button>
      </div>

      <div class="tab-group">
        <span class="tab-group-label">系统</span>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'config' }"
          @click="switchTab('config')"
          v-if="!isResourceAdminOnly"
        >⚙️ 系统配置</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'services' }"
          @click="switchTab('services')"
          v-if="userStore.isRoot"
        >🔧 服务管理</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'monitor' }"
          @click="switchTab('monitor')"
          v-if="!isResourceAdminOnly"
        >📈 系统监控</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'logs' }"
          @click="switchTab('logs')"
          v-if="userStore.isAdmin"
        >📜 系统日志</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'sync' }"
          @click="switchTab('sync')"
          v-if="!isResourceAdminOnly"
        >🔄 开发同步</button>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'scripts' }"
          @click="switchTab('scripts')"
          v-if="userStore.isAdmin"
        >📦 外部脚本</button>
      </div>

      <div class="tab-group">
        <span class="tab-group-label">账号</span>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'users' }"
          @click="switchTab('users')"
          v-if="userStore.isRoot"
        >👥 用户管理</button>
      </div>
    </div>

    <div class="admin-content">
      <!-- 回收站标签页 -->
      <div v-if="activeTab === 'trash'" class="tab-content">
        <div class="card">
          <div class="card-header">
            <h3>回收站</h3>
            <div class="header-actions">
              <button class="btn btn-primary" @click="loadTrash" :disabled="trashLoading">刷新</button>
              <button class="btn btn-danger" @click="emptyTrash" :disabled="trashItems.length === 0">清空回收站</button>
            </div>
          </div>
          <div v-if="trashLoading" class="empty-tip">加载中…</div>
          <div v-else-if="trashItems.length === 0" class="empty-tip">回收站为空</div>
          <table v-else class="data-table">
            <thead>
              <tr>
                <th>类型</th>
                <th>标题</th>
                <th>上传者</th>
                <th>删除时间</th>
                <th>大小</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in trashItems" :key="item.type + item.hash">
                <td>{{ item.type === 'video' ? '视频' : '图集' }}</td>
                <td class="cell-title">{{ item.title }}</td>
                <td>{{ item.owner || '—' }}</td>
                <td>{{ formatTrashTime(item.trashed_at) }}</td>
                <td>{{ formatSize(item.size) }}</td>
                <td class="cell-actions">
                  <button class="btn btn-primary btn-sm" @click="restoreTrashItem(item)">恢复</button>
                  <button class="btn btn-danger btn-sm" @click="purgeTrashItem(item)">永久删除</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

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

          <!-- 热门视频排行卡片 -->
          <div class="info-card hot-card" v-if="hotStats">
            <div class="card-header">
              <h3>热门视频</h3>
            </div>
            <div class="card-body">
              <div class="hot-col">
                <div class="hot-col-title">点赞最多</div>
                <div
                  v-for="(v, i) in (hotStats.top_liked || []).slice(0, 5)"
                  :key="v.hash"
                  class="hot-item"
                  @click="router.push('/video/' + v.hash)"
                >
                  <span class="hot-rank">{{ i + 1 }}</span>
                  <span class="hot-name" :title="v.title">{{ v.title }}</span>
                  <span class="hot-count">{{ v.like_count }}</span>
                </div>
                <div v-if="!(hotStats.top_liked && hotStats.top_liked.length)" class="hot-empty">暂无数据</div>
              </div>
              <div class="hot-col">
                <div class="hot-col-title">收藏最多</div>
                <div
                  v-for="(v, i) in (hotStats.top_favorited || []).slice(0, 5)"
                  :key="v.hash"
                  class="hot-item"
                  @click="router.push('/video/' + v.hash)"
                >
                  <span class="hot-rank fav">{{ i + 1 }}</span>
                  <span class="hot-name" :title="v.title">{{ v.title }}</span>
                  <span class="hot-count">{{ v.favorite_count }}</span>
                </div>
                <div v-if="!(hotStats.top_favorited && hotStats.top_favorited.length)" class="hot-empty">暂无数据</div>
              </div>
            </div>
          </div>

          <!-- 资源库分布卡片 -->
          <div class="info-card libdist-card" v-if="hotStats">
            <div class="card-header">
              <h3>资源库分布</h3>
            </div>
            <div class="card-body">
              <div class="stat-item" v-for="lib in hotStats.by_library" :key="lib.id">
                <div class="stat-info">
                  <span class="stat-value">{{ lib.count }}</span>
                  <span class="stat-label">{{ lib.name }}</span>
                </div>
              </div>
              <div v-if="!(hotStats.by_library && hotStats.by_library.length)" class="hot-empty">暂无资源库</div>
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

      </div>

      <!-- 开发同步标签页 -->
      <div v-if="activeTab === 'sync'" class="tab-content">
        <div class="section-header">
          <h3>开发同步</h3>
        </div>
        <div class="card-grid">
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
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
                  {{ isSyncing ? '同步中...' : '立即全量同步' }}
                </button>
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
            <!-- 资源库筛选 -->
            <select
              v-model="resourceLibraryFilter"
              @change="fetchVideos()"
              class="search-input"
              style="min-width: 140px"
            >
              <option value="">全部资源库</option>
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
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/><line x1="10" y1="3" x2="8" y2="21"/><line x1="16" y1="3" x2="14" y2="21"/></svg>
              批量设置优先级 ({{ selectedVideos.length }})
            </button>
            <button
              class="action-btn danger"
              @click="openBatchDeleteConfirm"
              :disabled="selectedVideos.length === 0"
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
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
      <AdminUsers v-if="activeTab === 'users'" />

      <!-- 系统配置标签页 -->
      <AdminConfig v-if="activeTab === 'config'" />

      <!-- 资源管理标签页（视频/图集/帖子/文本 按子标签切换，各自展示独有属性，管理员可编辑/删除任意资源） -->
      <div v-if="activeTab === 'resources'" class="tab-content">
        <div class="section-header">
          <h3>资源管理 <span class="muted">（按类型切换，管理员可编辑/删除任意资源）</span></h3>
          <div class="section-actions">
            <select v-model="resourceLibraryFilter" @change="fetchResources()" class="search-select">
              <option value="">全部资源库</option>
              <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
            </select>
            <input
              v-model="resourceSearch"
              @keyup.enter="fetchResources()"
              type="text"
              placeholder="搜索标题..."
              class="search-input"
            />
            <button class="action-btn" @click="fetchResources()">搜索</button>
          </div>
        </div>

        <!-- 资源类型子标签（按钮切换） -->
        <div class="subtab-group">
          <button
            class="subtab-btn"
            :class="{ active: resourceTypeFilter === '' }"
            @click="resourceTypeFilter = ''; fetchResources()"
          >全部</button>
          <button
            class="subtab-btn"
            :class="{ active: resourceTypeFilter === 'video' }"
            @click="resourceTypeFilter = 'video'; fetchResources()"
          >🎬 视频</button>
          <button
            class="subtab-btn"
            :class="{ active: resourceTypeFilter === 'gallery' }"
            @click="resourceTypeFilter = 'gallery'; fetchResources()"
          >🖼️ 图集</button>
          <button
            class="subtab-btn"
            :class="{ active: resourceTypeFilter === 'post' }"
            @click="resourceTypeFilter = 'post'; fetchResources()"
          >📝 帖子</button>
          <button
            class="subtab-btn"
            :class="{ active: resourceTypeFilter === 'text' }"
            @click="resourceTypeFilter = 'text'; fetchResources()"
          >📄 文本</button>
        </div>

        <!-- 显示隐藏资源开关（公共层属性 resource_index.hidden） -->
        <label class="show-hidden-toggle">
          <input type="checkbox" v-model="showHiddenResources" @change="fetchResources()" />
          <span>显示已隐藏的资源</span>
        </label>

        <div v-if="resourceLoading" class="loading">加载中...</div>
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>类型</th>
              <th>标题</th>
              <!-- 视频独有属性 -->
              <th v-if="resourceTypeFilter === '' || resourceTypeFilter === 'video'">大小</th>
              <th v-if="resourceTypeFilter === '' || resourceTypeFilter === 'video'">时长</th>
              <th v-if="resourceTypeFilter === '' || resourceTypeFilter === 'video'">分辨率</th>
              <!-- 图集独有属性 -->
              <th v-if="resourceTypeFilter === 'gallery'">图片个数</th>
              <!-- 帖子独有属性 -->
              <th v-if="resourceTypeFilter === 'post'">正文字数</th>
              <!-- 文本独有属性 -->
              <th v-if="resourceTypeFilter === 'text'">字数</th>
              <th>资源库</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in resources" :key="r.type + ':' + r.id">
              <td class="res-type">
                <span class="type-badge" :class="'type-' + r.type">
                  <span class="type-badge-icon">{{ typeIcon(r.type) }}</span>{{ typeLabel(r.type) }}
                </span>
              </td>
              <td class="res-title">
                <img v-if="r.cover" :src="withThumbToken(r.cover)" class="res-thumb" @error="(e:any)=>e.target.style.display='none'" />
                <span :title="r.title">{{ r.title }}</span>
                <span v-if="r.hidden" class="hidden-badge">已隐藏</span>
              </td>
              <!-- 视频独有属性 -->
              <td v-if="resourceTypeFilter === '' || resourceTypeFilter === 'video'">{{ formatSize(r.file_size) }}</td>
              <td v-if="resourceTypeFilter === '' || resourceTypeFilter === 'video'">{{ formatDuration(r.duration) }}</td>
              <td v-if="resourceTypeFilter === '' || resourceTypeFilter === 'video'">{{ formatResolution(r.width, r.height) }}</td>
              <!-- 图集独有属性 -->
              <td v-if="resourceTypeFilter === 'gallery'">{{ formatCount(r.page_count) }}</td>
              <!-- 帖子独有属性 -->
              <td v-if="resourceTypeFilter === 'post'">{{ formatCount(r.content_length) }}</td>
              <!-- 文本独有属性 -->
              <td v-if="resourceTypeFilter === 'text'">{{ formatCount(r.char_count) }}</td>
              <td>{{ libraryName(r.library_id) }}</td>
              <td>{{ formatDate(r.updated_at) }}</td>
              <td class="row-actions">
                <button
                  class="icon-btn"
                  :class="{ active: r.hidden }"
                  @click="toggleResourceHidden(r)"
                  :title="r.hidden ? '已隐藏，点击显示' : '点击隐藏'"
                  :disabled="togglingHidden === r.resource_index_id"
                >{{ r.hidden ? '👁️' : '🙈' }}</button>
                <button class="icon-btn" @click="editResource(r)" title="编辑">✏️</button>
                <button class="icon-btn danger" @click="deleteResource(r)" title="删除">🗑️</button>
              </td>
            </tr>
            <tr v-if="resources.length === 0"><td :colspan="resourceColspan" class="empty">暂无资源</td></tr>
          </tbody>
        </table>

        <div v-if="resourceTotal > RESOURCE_PAGE_SIZE" class="pagination">
          <button class="page-btn" :disabled="resourcePage <= 1" @click="resourcePage--; fetchResources(false)">上一页</button>
          <span class="page-info">第 {{ resourcePage }} / {{ Math.ceil(resourceTotal / RESOURCE_PAGE_SIZE) }} 页（共 {{ resourceTotal }} 条）</span>
          <button class="page-btn" :disabled="resourcePage >= Math.ceil(resourceTotal / RESOURCE_PAGE_SIZE)" @click="resourcePage++; fetchResources(false)">下一页</button>
        </div>
      </div>

      <!-- 外部脚本标签页 -->
      <AdminScripts v-if="activeTab === 'scripts'" />

      <!-- 缩略图管理标签页 -->
      <div v-if="activeTab === 'thumbnail'" class="tab-content">
        <div class="section-header">
          <h3>缩略图管理</h3>
          <div class="section-actions">
            <button
              class="action-btn primary"
              @click="triggerGenerateMissing"
              :disabled="thumbGenerating || thumbStats.no_thumbnail_count === 0"
            >
              {{ thumbGenerating ? '生成中...' : '立即生成缺失缩略图' }}
              <span v-if="thumbStats.no_thumbnail_count > 0" class="badge-count">
                {{ thumbStats.no_thumbnail_count }}
              </span>
            </button>
          </div>
        </div>

        <div v-if="thumbLoading && !thumbConfigLoaded" class="loading-placeholder">
          <div class="loading-spinner"></div>
          <p>加载中...</p>
        </div>

        <div v-else>
          <!-- 统计概览 -->
          <div class="thumb-stats-grid">
            <div class="thumb-stat-card">
              <div class="stat-icon">🎬</div>
              <div class="stat-info">
                <span class="stat-value">{{ thumbStats.total_videos }}</span>
                <span class="stat-label">总视频数</span>
              </div>
            </div>
            <div class="thumb-stat-card">
              <div class="stat-icon">🖼️</div>
              <div class="stat-info">
                <span class="stat-value">{{ thumbStats.total_thumbnails }}</span>
                <span class="stat-label">已有缩略图</span>
              </div>
            </div>
            <div class="thumb-stat-card" :class="{ 'stat-warning': thumbStats.no_thumbnail_count > 0 }">
              <div class="stat-icon">⚠️</div>
              <div class="stat-info">
                <span class="stat-value">{{ thumbStats.no_thumbnail_count }}</span>
                <span class="stat-label">缺失缩略图</span>
              </div>
            </div>
            <div class="thumb-stat-card">
              <div class="stat-icon">🔧</div>
              <div class="stat-info">
                <span class="stat-value" :class="thumbServiceStatusClass(thumbStats.thumb_service_status)">
                  {{ thumbServiceStatusText(thumbStats.thumb_service_status) }}
                </span>
                <span class="stat-label">缩略图服务</span>
              </div>
            </div>
          </div>

          <!-- 缩略图服务任务状态 -->
          <div v-if="thumbStats.thumb_service_stats" class="thumb-service-detail">
            <h4>服务任务状态</h4>
            <div class="task-stats-row">
              <span>已完成: <b>{{ thumbStats.thumb_service_stats.tasks_completed }}</b></span>
              <span>失败: <b class="text-error">{{ thumbStats.thumb_service_stats.tasks_failed }}</b></span>
              <span>执行中: <b>{{ thumbStats.thumb_service_stats.active_tasks }}</b></span>
              <span>队列中: <b>{{ thumbStats.thumb_service_stats.queue_size }}</b></span>
            </div>
          </div>

          <!-- 配置表单 -->
          <div class="config-form thumb-config-form">
            <h4 class="config-section-title">生成设置</h4>

            <!-- 自动生成开关 -->
            <div class="form-group form-row">
              <div class="form-label-area">
                <label>自动生成缺失缩略图</label>
                <span class="form-hint">开启后会定期扫描没有缩略图的视频并自动生成</span>
              </div>
              <label class="switch">
                <input v-model="thumbConfig.auto_generate" type="checkbox" />
                <span class="slider"></span>
              </label>
            </div>

            <!-- 自动生成运行状态 -->
            <div v-if="thumbStats.is_auto_generating" class="auto-status-banner running">
              <div class="auto-status-dot"></div>
              <span>自动生成正在运行中</span>
              <button class="action-btn danger small" @click="stopAutoGenerate">停止</button>
            </div>

            <!-- 并发线程数 -->
            <div class="form-group">
              <label>最大并发线程数</label>
              <div class="input-with-hint">
                <input
                  v-model.number="thumbConfig.max_workers"
                  type="number"
                  min="1"
                  max="8"
                  step="1"
                />
                <span class="input-hint">1-8，建议 1-3，值越大 CPU 占用越高</span>
              </div>
            </div>

            <!-- 任务间隔 -->
            <div class="form-group">
              <label>任务间隔时间</label>
              <div class="input-with-hint">
                <input
                  v-model.number="thumbConfig.task_interval"
                  type="number"
                  min="1"
                  max="60"
                  step="1"
                />
                <span class="input-hint">1-60 秒，每个生成任务之间的等待时间</span>
              </div>
            </div>

            <!-- 自动扫描间隔（仅当 auto_generate 开启时显示） -->
            <div class="form-group" v-if="thumbConfig.auto_generate">
              <label>自动扫描间隔</label>
              <div class="input-with-hint">
                <input
                  v-model.number="thumbConfig.auto_generate_interval"
                  type="number"
                  min="300"
                  max="86400"
                  step="300"
                />
                <span class="input-hint">{{ formatInterval(thumbConfig.auto_generate_interval) }}，5分钟 ~ 24小时</span>
              </div>
            </div>

            <div class="form-actions">
              <button class="action-btn primary" @click="saveThumbnailConfig" :disabled="thumbSaving">
                {{ thumbSaving ? '保存中...' : '保存配置' }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 服务管理标签页 -->
      <div v-if="activeTab === 'services'" class="tab-content">
        <div class="section-header">
          <h3>服务管理</h3>
          <div class="section-actions">
            <span class="auto-refresh-hint">自动刷新中</span>
            <button class="action-btn" @click="fetchServices()" :disabled="servicesLoading">
              {{ servicesLoading ? '刷新中...' : '手动刷新' }}
            </button>
          </div>
        </div>

        <div v-if="servicesLoading && services.length === 0" class="loading-placeholder">
          <div class="loading-spinner"></div>
          <p>扫描服务中...</p>
        </div>

        <div v-else-if="services.length === 0" class="empty-state">
          <p>未发现 dplayer- 前缀的 NSSM 服务</p>
        </div>

        <div v-else class="services-list">
          <div
            v-for="svc in services"
            :key="svc.service_name"
            class="service-card"
            :class="{ 'svc-card-operating': isOperating(svc.service_name) }"
          >
            <!-- 服务头部 -->
            <div class="svc-header">
              <div class="svc-title-area">
                <h4>{{ svc.display_name }}</h4>
                <span class="svc-name-tag">{{ svc.service_name }}</span>
              </div>
              <div class="svc-status-lights">
                <!-- 系统层健康灯 -->
                <div
                  class="health-light"
                  :class="systemStatusClass(svc.system_status)"
                  :title="'系统状态: ' + systemStatusText(svc.system_status)"
                >
                  <span class="light-dot"></span>
                  <span class="light-label">系统</span>
                </div>
                <!-- 服务层健康灯 -->
                <div
                  class="health-light"
                  :class="healthStatusClass(svc.health_status)"
                  :title="'服务状态: ' + (svc.health_status === 'healthy' ? '正常' : svc.health_status)"
                >
                  <span class="light-dot"></span>
                  <span class="light-label">服务</span>
                </div>
              </div>
            </div>

            <!-- 服务详情 -->
            <div class="svc-details">
              <div class="svc-desc">{{ svc.description }}</div>

              <div class="svc-metrics">
                <!-- 系统状态 -->
                <div class="metric-item">
                  <span class="metric-label">系统状态</span>
                  <span class="metric-value" :class="systemStatusClass(svc.system_status)">
                    {{ systemStatusText(svc.system_status) }}
                  </span>
                </div>
                <!-- 服务层健康 -->
                <div class="metric-item">
                  <span class="metric-label">服务健康</span>
                  <span class="metric-value">
                    {{ healthStatusIcon(svc.health_status) }}
                    <span :class="healthStatusClass(svc.health_status)">{{ svc.health_status === 'healthy' ? '正常' : svc.health_status === 'unhealthy' ? '异常' : '未知' }}</span>
                  </span>
                </div>
                <!-- PID -->
                <div class="metric-item">
                  <span class="metric-label">PID</span>
                  <span class="metric-value mono">{{ svc.pid ?? '-' }}</span>
                </div>
                <!-- 内存 -->
                <div class="metric-item">
                  <span class="metric-label">内存</span>
                  <span class="metric-value mono">{{ svc.memory_mb != null ? svc.memory_mb + ' MB' : '-' }}</span>
                </div>
                <!-- CPU -->
                <div class="metric-item">
                  <span class="metric-label">CPU</span>
                  <span class="metric-value mono">{{ svc.cpu_percent != null ? svc.cpu_percent + '%' : '-' }}</span>
                </div>
                <!-- 端口 -->
                <div class="metric-item">
                  <span class="metric-label">端口</span>
                  <span class="metric-value mono">:{{ svc.port }}</span>
                </div>
                <!-- 延迟 -->
                <div class="metric-item" v-if="svc.health_latency_ms != null">
                  <span class="metric-label">延迟</span>
                  <span class="metric-value mono">{{ svc.health_latency_ms }} ms</span>
                </div>
              </div>

              <!-- 服务层详情 -->
              <div v-if="svc.health_detail" class="svc-health-detail">
                {{ svc.health_detail }}
              </div>
            </div>

            <!-- 操作按钮 -->
            <div class="svc-actions">
              <!-- 启动中 / 停止中：只显示 loading -->
              <template v-if="isOperating(svc.service_name)">
                <div class="svc-operating-indicator">
                  <div class="loading-spinner small"></div>
                  <span>操作中...</span>
                </div>
              </template>
              <!-- 已停止/暂停：显示启动按钮 -->
              <template v-else-if="canStart(svc)">
                <button
                  class="action-btn primary"
                  @click="controlService(svc.service_name, 'start')"
                  :disabled="isOperating(svc.service_name)"
                >
                  ▶ 启动
                </button>
              </template>
              <!-- 运行中：显示停止和重启 -->
              <template v-else-if="canStop(svc)">
                <button
                  class="action-btn danger"
                  @click="controlService(svc.service_name, 'stop')"
                  :disabled="isOperating(svc.service_name)"
                >
                  ⏹ 停止
                </button>
                <button
                  class="action-btn"
                  @click="controlService(svc.service_name, 'restart')"
                  :disabled="isOperating(svc.service_name)"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
                  重启
                </button>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- 资源库管理标签页 -->
      <div v-if="activeTab === 'libraries'" class="tab-content">
        <div class="section-header">
          <h3>资源库管理</h3>
          <div class="header-actions">
            <button class="action-btn" @click="scanAllLibraries()" :disabled="scanAllScanning" v-if="userStore.isAdmin">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
              {{ scanAllScanning ? '全量扫描中...' : '🔄 扫描全部库（同步文件名/标题）' }}
            </button>
            <button class="action-btn primary" @click="editingLibrary = null; showLibraryModal = true" v-if="userStore.isAdmin">+ 新建资源库</button>
          </div>
        </div>
        <div v-if="scanAllMessage" class="scan-all-status">{{ scanAllMessage }}</div>

        <!-- 资源库列表 -->
        <div class="library-grid">
          <div v-for="lib in libraries" :key="lib.id" class="library-card">
            <div class="library-card-header">
              <h4>{{ lib.name }}</h4>
              <!-- 右上角激活/禁用按钮 -->
              <button
                :class="['toggle-active-btn', lib.is_active ? 'active' : 'inactive']"
                @click="toggleLibraryActive(lib)"
                :title="lib.is_active ? '点击禁用' : '点击激活'"
                v-if="userStore.isAdmin"
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
              <button
                :class="['action-btn', 'primary', { active: expandedLibraryId === lib.id }]"
                @click="expandedLibraryId === lib.id ? leaveLibraryDetail() : enterLibraryDetail(lib)"
                :title="expandedLibraryId === lib.id ? '收起详情' : '展开查看资源库详情、关联文件夹与文件列表'"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
                导入
              </button>
              <button class="action-btn" @click="editLibrary(lib)" title="编辑" v-if="userStore.isAdmin">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                编辑
              </button>
              <button class="action-btn" @click="fetchLibraryPermissions(lib.id); showPermissionModal = true" title="权限设置" v-if="userStore.isAdmin">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                权限
              </button>
              <button class="action-btn" @click="manageFolders(lib)" title="管理文件夹">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
                文件夹
              </button>
              <button class="action-btn danger" @click="deleteLibrary(lib.id)" title="删除" v-if="userStore.isAdmin">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                删除
              </button>
            </div>
          </div>
        </div>

        <div v-if="libraries.length === 0 && !loading.libraries" class="empty-state">
          <p>暂无资源库，请创建一个</p>
        </div>

      </div>

      <!-- ============ 资源库导入弹窗（替代原向下展开 + 独立批量导入Tab） ============ -->
      <div v-if="expandedLibraryId" class="modal-overlay" @click="leaveLibraryDetail()">
        <div class="modal-content import-modal" @click.stop>
          <div class="modal-header import-modal-header">
            <div class="import-modal-title">
              <h3>{{ currentLibrary?.name || '资源库' }} · 导入视频</h3>
              <p class="modal-subtitle" v-if="currentLibrary?.description">{{ currentLibrary.description }}</p>
            </div>
            <button class="close-btn" @click="leaveLibraryDetail()">×</button>
          </div>

          <div class="modal-body import-modal-body">
            <!-- 扫描控制：固定顶部，与文件列表分离 -->
            <div class="import-toolbar">
              <button
                class="action-btn primary"
                @click="scanDetailFolder()"
                :disabled="libraryDetailScanning || libraryDetailImporting || libraryDetailFolders.length === 0"
                :title="libraryDetailFolders.length === 0 ? '该库没有关联文件夹，请使用“选择其他文件夹”' : '扫描该库关联文件夹中的视频'"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                {{ libraryDetailScanning ? '扫描中...' : '扫描关联文件夹' }}
              </button>
              <button
                class="action-btn"
                @click="openLibraryImportFolderBrowser()"
                :disabled="libraryDetailScanning || libraryDetailImporting"
              >
                📂 选择其他文件夹…
              </button>
              <span v-if="libraryDetailScanInfo" class="scan-progress-inline">正在扫描：{{ libraryDetailScanInfo.folder }}（{{ libraryDetailScanInfo.index }}/{{ libraryDetailScanInfo.total }}，已发现 {{ libraryDetailScanInfo.found }}）</span>
              <span v-else-if="libraryDetailScanning" class="scan-progress-inline">正在准备扫描…</span>
            </div>

            <!-- 扫描汇总 -->
            <div v-if="libraryDetailScanSummary" class="scan-summary-banner">
              <span class="scan-summary-text">
                扫描完成：共 <b>{{ libraryDetailScanSummary.total }}</b> 个视频，
                <b class="new-count">{{ libraryDetailScanSummary.newCount }}</b> 个新视频，
                {{ libraryDetailScanSummary.existCount }} 个已存在
              </span>
            </div>

            <!-- 扫描失败提示 -->
            <div v-if="libraryDetailScanErrors.length > 0" class="scan-error-banner">
              <div class="scan-error-title">⚠️ {{ libraryDetailScanErrors.length }} 个文件夹扫描失败：</div>
              <ul class="scan-error-list">
                <li v-for="(err, idx) in libraryDetailScanErrors" :key="idx">
                  <b>{{ err.folder }}</b>：{{ err.message }}
                </li>
              </ul>
            </div>

            <!-- 关联文件夹标签页 -->
            <div class="detail-folders-section" v-if="libraryDetailFolders.length > 0">
              <h4>关联文件夹</h4>
              <div class="folder-tabs">
                <button
                  :class="['folder-tab', { active: libraryDetailFolderKey === '__all__' }]"
                  @click="libraryDetailFolderKey = '__all__'"
                >
                  所有
                  <span class="tab-count" v-if="libraryDetailFileCache['__all__']">
                    {{ libraryDetailFileCache['__all__'].length }}
                  </span>
                </button>
                <button
                  v-for="folder in libraryDetailFolders"
                  :key="getFolderKey(folder)"
                  :class="['folder-tab', { active: libraryDetailFolderKey === getFolderKey(folder) }]"
                  @click="libraryDetailFolderKey = getFolderKey(folder)"
                >
                  {{ getFolderLabel(folder) }}
                  <span class="tab-count" v-if="libraryDetailFileCache[getFolderKey(folder)]">
                    {{ libraryDetailFileCache[getFolderKey(folder)].length }}
                  </span>
                </button>
              </div>
            </div>

            <!-- 扫描中 -->
            <div v-if="(libraryDetailScanning || libraryDetailImporting) && !libraryDetailCurrentFiles.length" class="loading-state">
              <div class="loading-spinner"></div>
              <span v-if="libraryDetailImporting" class="scan-progress">正在导入视频...</span>
              <span v-else-if="libraryDetailScanInfo" class="scan-progress">正在扫描：{{ libraryDetailScanInfo.folder }}</span>
              <span v-else class="scan-progress">正在准备扫描...</span>
            </div>

            <!-- 文件列表（可滚动） -->
            <div v-if="libraryDetailCurrentFiles.length > 0" class="scan-results import-results">
              <div class="video-list import-video-list">
                <div
                  v-for="video in libraryDetailCurrentFiles"
                  :key="video.path"
                  :class="['video-item', { selected: libraryDetailSelectedFiles.includes(video.path), existing: video.exists }]"
                  @click="!video.exists && detailToggleFile(video.path)"
                >
                  <div class="video-checkbox">
                    <input
                      v-if="!video.exists"
                      type="checkbox"
                      :checked="libraryDetailSelectedFiles.includes(video.path)"
                      @click.stop
                      @change="detailToggleFile(video.path)"
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
              <div v-if="libraryDetailImporting" class="import-progress-inline">
                正在导入…（已导入 {{ libraryDetailImportProgress.imported }}，跳过 {{ libraryDetailImportProgress.skipped }}）
              </div>
            </div>

            <!-- 未扫描引导 -->
            <div v-else-if="!libraryDetailScanning && !libraryDetailImporting && libraryDetailFolders.length > 0 && !libraryDetailFileCache[libraryDetailFolderKey]" class="empty-state">
              <div class="empty-icon">📂</div>
              <div class="empty-text">点击上方“扫描”按钮开始扫描</div>
              <div class="empty-hint">将扫描 {{ libraryDetailFolderKey === '__all__' ? '所有关联文件夹' : '当前文件夹' }} 中的视频文件</div>
            </div>
          </div>

          <!-- 底部固定操作条：全选 + 已选数 + 导入 同处一行 -->
          <div class="modal-footer import-action-bar" v-if="libraryDetailCurrentFiles.length > 0">
            <label class="checkbox-label select-all">
              <input
                type="checkbox"
                :checked="libraryDetailSelectedFiles.length > 0 && libraryDetailSelectedFiles.length === libraryDetailCurrentFiles.filter((v: any) => !v.exists).length"
                @change="detailToggleSelectAll"
              />
              <span>{{ libraryDetailSelectedFiles.length === libraryDetailCurrentFiles.filter((v: any) => !v.exists).length ? '取消全选' : '全选' }}</span>
            </label>
            <span class="selected-count">
              已选择 {{ libraryDetailSelectedFiles.length }} / {{ libraryDetailCurrentFiles.filter((v: any) => !v.exists).length }} 个新视频
            </span>
            <button
              class="action-btn primary large"
              @click="detailImportVideos"
              :disabled="libraryDetailImporting || libraryDetailSelectedFiles.length === 0"
            >
              {{ libraryDetailImporting ? '导入中...' : `导入 ${libraryDetailSelectedFiles.length} 个视频` }}
            </button>
          </div>
        </div>
      </div>

      <AdminLogs v-if="activeTab === 'logs'" />

      <AdminMonitor v-if="activeTab === 'monitor'" />
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
          <div class="form-group">
            <label>标签（用 "/" 分隔层级）</label>
            <input 
              v-model="editingVideoTags" 
              type="text" 
              placeholder="例如: 动物 / 狗 / 哈士奇"
            />
            <small class="form-hint">用 "/" 分隔表示层级，如 "/动物/狗" 是 "/动物" 的子标签</small>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showVideoEditModal = false">取消</button>
          <button class="action-btn primary" @click="saveVideoEdit">保存</button>
        </div>
      </div>
    </div>

    <!-- 资源编辑弹窗（统一：视频/图集/帖子/文本） -->
    <div v-if="showResourceEditModal" class="modal-overlay" @click="showResourceEditModal = false">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>编辑{{ editingResource ? resourceTypeLabel(editingResource.type) : '' }}（管理员）</h3>
          <button class="close-btn" @click="showResourceEditModal = false">×</button>
        </div>
        <div class="modal-body" v-if="editingResource">
          <div class="form-group">
            <label>标题</label>
            <input v-model="editingResource.title" class="form-input" />
          </div>
          <div class="form-group" v-if="editingResource.type === 'post'">
            <label>正文</label>
            <textarea v-model="editingResource.content" class="form-input" rows="8"></textarea>
          </div>
          <div class="form-group" v-if="editingResource.type === 'text'">
            <label>简介</label>
            <input v-model="editingResource.summary" class="form-input" />
            <label>正文</label>
            <textarea v-model="editingResource.body" class="form-input" rows="8"></textarea>
          </div>
          <div class="form-group" v-if="editingResource.type === 'video' || editingResource.type === 'gallery'">
            <p class="muted">该资源类型仅支持修改标题（其余字段由存储与元数据决定）。</p>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showResourceEditModal = false">取消</button>
          <button class="action-btn primary" @click="saveResourceEdit">保存</button>
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

    <!-- 资源库编辑弹窗 -->
    <div v-if="showLibraryModal" class="modal-overlay" @click="showLibraryModal = false">
      <div class="modal-content library-modal" @click.stop>
        <div class="modal-header">
          <h3>{{ editingLibrary ? '✏️ 编辑资源库' : '📁 新建资源库' }}</h3>
          <button class="close-btn" @click="showLibraryModal = false">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>资源库名称 <span class="required">*</span></label>
            <input 
              v-if="editingLibrary" 
              v-model="editingLibrary.name" 
              type="text" 
              placeholder="请输入资源库名称"
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
              placeholder="请输入资源库描述（可选）"
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
            <span v-else>{{ editingLibrary ? '保存修改' : '创建资源库' }}</span>
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

    <!-- 文件夹管理弹窗 -->
    <div v-if="showFolderModal" class="modal-overlay" @click="showFolderModal = false">
      <div class="modal-content modal-large" @click.stop>
        <div class="modal-header">
          <h3>📁 文件夹管理</h3>
          <button class="close-btn" @click="showFolderModal = false">×</button>
        </div>
        <div class="modal-body">
          <!-- 添加文件夹表单 -->
          <div class="folder-form card">
            <h4>添加扫描路径</h4>
            <div class="form-group">
              <label>路径 <span class="required">*</span></label>
              <div class="input-with-button">
                <input v-model="folderForm.path" type="text" placeholder="点击浏览选择文件或文件夹" readonly />
                <button class="action-btn" @click="openFolderBrowserForAdd">📂 浏览...</button>
              </div>
              <small v-if="folderForm.path" class="form-hint">
                {{ folderForm.path_type === 'file' ? '📄 文件' : '📁 文件夹' }}
              </small>
            </div>
            <div class="form-group">
              <label class="checkbox-label">
                <input v-model="folderForm.is_default" type="checkbox" />
                设为默认上传路径
              </label>
            </div>
            <div class="form-actions">
              <button class="action-btn primary" @click="addLibraryFolder" :disabled="!folderForm.path">添加</button>
            </div>
          </div>

          <!-- 文件夹列表 -->
          <div class="folder-list-section">
            <h4>已配置的文件夹</h4>
            <div v-if="libraryFolders.length === 0" class="empty-state">
              <p>暂无文件夹，请添加扫描路径</p>
            </div>
            <div v-else class="folder-items">
              <div v-for="folder in libraryFolders" :key="folder.id" class="folder-item card">
                <div class="folder-info">
                  <div class="folder-name">
                    <span v-if="folder.is_default" class="default-badge">默认</span>
                    <span class="folder-type-icon">{{ folder.path_type === 'file' ? '📄' : '📁' }}</span>
                    {{ folder.path }}
                  </div>
                  <div class="folder-meta">
                    <span>扫描: {{ folder.item_count || 0 }} 个</span>
                    <span v-if="folder.last_scan_at">最后: {{ folder.last_scan_at }}</span>
                  </div>
                </div>
                <div class="folder-actions">
                  <button
                    v-if="!folder.is_default"
                    class="action-btn"
                    @click="setAsDefaultFolder(folder.id)"
                    title="设为默认上传路径"
                  >
                    ⭐设为默认
                  </button>
                  <button
                    class="action-btn danger"
                    @click="deleteLibraryFolder(folder.id)"
                  >
                    🗑️删除
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showFolderModal = false">关闭</button>
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

          <!-- 新建文件夹 -->
          <div class="new-folder-row">
            <input
              v-model="newFolderName"
              class="new-folder-input"
              placeholder="输入新文件夹名称后点击新建"
              @keyup.enter="createFolderInBrowser"
            />
            <button class="action-btn" @click="createFolderInBrowser">新建文件夹</button>
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
                :class="['folder-item', { 'folder-item-file': item.type === 'file' }]"
                @click="item.type === 'file' ? selectFileFromBrowser(item) : enterFolder(item)"
              >
                <div class="folder-icon">
                  {{ item.type === 'drive' ? '💿' : item.type === 'file' ? '📄' : '📁' }}
                </div>
                <div class="folder-info">
                  <div class="folder-name">{{ item.display || item.name }}</div>
                  <div class="folder-type">
                    {{ item.type === 'drive' ? '驱动器' : item.type === 'file' ? '文件' : '文件夹' }}
                  </div>
                </div>
                <div class="folder-arrow">{{ item.type === 'file' ? '' : '▶' }}</div>
              </div>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showFolderBrowser = false">取消</button>
          <button
            v-if="browserMode === 'folder'"
            class="action-btn primary"
            @click="browserPurpose === 'addFolder' ? selectPathFromBrowser() : selectCurrentFolder()"
            :disabled="!browserPath"
          >
            选择此文件夹
          </button>
          <button
            v-else
            class="action-btn primary"
            @click="selectPathFromBrowser"
            :disabled="!browserPath"
          >
            选择此路径
          </button>
        </div>
      </div>
    </div>

    <!-- 用户创建/编辑弹窗 -->
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

    <!-- Toast 提示 -->
    <div v-if="showToastFlag" class="toast">{{ toastMessage }}</div>
  </div>
</template>

<style>
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
  background: #23232f;
  border-radius: 12px;
  padding: 24px;
  min-width: 360px;
  max-width: 480px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
}

.dialog h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
  color: #e6edf3;
}

.dialog p {
  margin: 0 0 16px 0;
  color: #8b949e;
  line-height: 1.5;
}

.dialog-checkbox {
  margin-bottom: 20px;
  padding: 12px;
  background: #2a2a38;
  border-radius: 8px;
}

.dialog-checkbox label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: #c9d1d9;
  font-size: 14px;
}

.dialog-checkbox input[type="checkbox"] {
  width: 16px;
  height: 16px;
  cursor: pointer;
}

.thumbnail-modal-ops {
  display: flex;
  gap: 12px;
  margin-bottom: 20px;
}

.thumbnail-modal-ops .action-btn {
  flex: 1;
  padding: 12px 16px;
  font-size: 14px;
}

.dialog-buttons {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}

.btn-secondary {
  padding: 8px 16px;
  background: #2a2a38;
  border: none;
  border-radius: 6px;
  color: #c9d1d9;
  cursor: pointer;
  font-size: 14px;
}

.btn-secondary:hover {
  background: #2d2d3f;
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

.admin-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #0d0d12 0%, #16161d 100%);
  padding: 24px;
}

.admin-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding: 16px 24px;
  background: #23232f;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.admin-header h1 {
  margin: 0;
  font-size: 24px;
  color: #e6edf3;
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
  color: #8b949e;
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
  background: #23232f;
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
  border-bottom: 1px solid #23232f;
}

.info-row:last-child {
  border-bottom: none;
}

.label {
  font-size: 13px;
  color: #8b949e;
}

.value {
  font-size: 13px;
  color: #c9d1d9;
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
  color: #8b949e;
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
  background: #16161d;
  border-radius: 8px;
}

.stat-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #23232f;
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
  color: #e6edf3;
}

.stat-label {
  font-size: 12px;
  color: #888;
}

/* 热门视频排行卡片 */
.hot-card .card-body {
  display: flex;
  gap: 20px;
}

.hot-col {
  flex: 1;
  min-width: 0;
}

.hot-col-title {
  font-size: 13px;
  font-weight: 600;
  color: #8b949e;
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid #2d2d3f;
}

.hot-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 4px;
  border-radius: 6px;
  cursor: pointer;
}

.hot-item:hover {
  background: #2a2a38;
}

.hot-rank {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  border-radius: 50%;
  background: #ff4757;
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hot-rank.fav {
  background: #ffa502;
}

.hot-name {
  flex: 1;
  font-size: 13px;
  color: #c9d1d9;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hot-count {
  font-size: 13px;
  font-weight: 600;
  color: #ff4757;
}

.hot-empty {
  font-size: 12px;
  color: #aaa;
  padding: 6px 4px;
}

.libdist-card .card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 同步卡片样式 */
.sync-actions {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid #23232f;
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
  background: #16161d;
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
  color: #c9d1d9;
  word-break: break-all;
}

/* 同步日志样式 */
.sync-log-section {
  background: #23232f;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: #16161d;
  border-bottom: 1px solid #2d2d3f;
}

.section-header h3 {
  margin: 0;
  font-size: 16px;
  color: #c9d1d9;
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.scan-all-status {
  padding: 8px 20px;
  font-size: 13px;
  color: #7ee787;
  background: #16241a;
  border-bottom: 1px solid #3a5a3a;
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
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 4px;
  padding: 0 24px 16px;
  background: #23232f;
  border-bottom: 1px solid #2d2d3f;
  margin: 0 -24px 24px;
}

.tab-group {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid #2d2d3f;
  border-radius: 10px;
  background: #1a1a24;
}

.tab-group-label {
  font-size: 12px;
  font-weight: 600;
  color: #999;
  padding: 0 6px 0 2px;
  letter-spacing: 1px;
  user-select: none;
}

.tab-btn {
  padding: 10px 20px;
  background: transparent;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  color: #8b949e;
  cursor: pointer;
  transition: all 0.3s ease;
}

.tab-btn:hover {
  background: #2a2a38;
  color: #c9d1d9;
}

.tab-btn.active {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.tab-content {
  animation: fadeIn 0.3s ease;
  display: flex;
  flex-direction: column;
  min-height: calc(100vh - 180px);
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
  border: 1px solid #2d2d3f;
  border-radius: 8px;
  font-size: 14px;
  width: 240px;
}

.search-select {
  padding: 8px 36px 8px 16px;
  border: 1px solid #2d2d3f;
  border-radius: 8px;
  font-size: 14px;
  background-color: #2a2a38;
  color: #e0e0e0;
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a0a0b0' stroke-width='2'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat: no-repeat;
  background-position: right 12px center;
  transition: border-color 0.3s ease, background-color 0.3s ease;
}

.search-select:hover {
  background-color: #32323f;
}

.search-select:focus {
  outline: none;
  border-color: #667eea;
}

.data-table-container {
  background: #23232f;
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

/* 资源管理标签页 */
.type-badge {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 10px;
  font-size: 12px;
  font-weight: 600;
  color: #fff;
}
.type-badge.type-video { background: #2196F3; }
.type-badge.type-gallery { background: #9C27B0; }
.type-badge.type-post { background: #FF9800; }
.type-badge.type-text { background: #4CAF50; }
.type-badge-icon { margin-right: 4px; }
.res-type { white-space: nowrap; }
.res-title { display: flex; align-items: center; gap: 10px; max-width: 420px; }
.res-thumb { width: 40px; height: 30px; object-fit: cover; border-radius: 4px; background: #2a2a2a; flex-shrink: 0; }
.res-title span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hidden-badge { background: #5a3a00; color: #ffcf66; border: 1px solid #806020; border-radius: 6px; padding: 1px 7px; font-size: 11px; flex-shrink: 0; }
.show-hidden-toggle { display: inline-flex; align-items: center; gap: 6px; margin: 10px 0 4px; color: #bbb; font-size: 13px; cursor: pointer; user-select: none; }
.show-hidden-toggle input { width: 15px; height: 15px; accent-color: #ffb300; }
.muted { color: #8b949e; font-weight: 400; font-size: 13px; }

.data-table th,
.data-table td {
  padding: 14px 16px;
  text-align: left;
  border-bottom: 1px solid #23232f;
}

.data-table th {
  background: #16161d;
  font-weight: 600;
  font-size: 13px;
  color: #8b949e;
  position: sticky;
  top: 0;
  z-index: 10;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.data-table th:hover {
  background: #1f1f29;
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
  color: #c9d1d9;
}

.data-table tbody tr {
  transition: background 0.15s ease;
}

.data-table tbody tr:hover {
  background: #12243a;
}

.data-table tbody tr.selected {
  background: #16335a;
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
  border: 3px solid #23232f;
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
  background: #23232f;
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
  color: #8b949e;
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
  background: #23232f;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.page-btn {
  padding: 8px 16px;
  border: 1px solid #d9d9d9;
  border-radius: 6px;
  background: #23232f;
  color: #c9d1d9;
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
  border-color: #23232f;
  cursor: not-allowed;
}

.page-info {
  font-size: 13px;
  color: #8b949e;
}

.video-thumb {
  width: 60px;
  height: 40px;
  object-fit: cover;
  border-radius: 4px;
}

/* 操作按钮 */
.action-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  background: #2a2a38;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.action-btn svg {
  flex-shrink: 0;
}

.action-btn:hover {
  background: #2d2d3f;
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

.action-btn.success {
  background: #52c41a;
  color: white;
}

.action-btn.success:hover {
  background: #73d13d;
}

/* 扫描进度反馈 */
.scan-progress {
  font-size: 14px;
  color: #c9d1d9;
  font-weight: 500;
}

.scan-progress-sub {
  font-size: 12px;
  color: #888;
}

/* 扫描结果汇总横幅 */
.scan-summary-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin: 16px 0;
  padding: 12px 16px;
  background: #16241a;
  border: 1px solid #3a5a3a;
  border-radius: 8px;
}

.scan-summary-text {
  font-size: 14px;
  color: #c9d1d9;
}

.scan-summary-text b {
  color: #52c41a;
}

.scan-summary-text .new-count {
  color: #fa8c16;
}

/* 扫描文件夹失败提示 */
.scan-error-banner {
  margin: 12px 0;
  padding: 12px 16px;
  background: #241f12;
  border: 1px solid #5a4a1a;
  border-radius: 8px;
}

.scan-error-title {
  font-size: 13px;
  color: #ffc53d;
  font-weight: 500;
  margin-bottom: 6px;
}

.scan-error-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: #ffd666;
}

.scan-error-list li {
  margin: 2px 0;
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
  background: #2a2a38;
}

.icon-btn.danger:hover {
  background: #2e1212;
}

/* 角色标签 */
.role-tag {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.role-tag.root {
  background: #2e1212;
  color: #ff7875;
}

.role-tag.admin {
  background: #121a2e;
  color: #69c0ff;
}

.role-tag.user {
  background: #16241a;
  color: #52c41a;
}

/* 配置表单 */
.config-form {
  background: #23232f;
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
  color: #c9d1d9;
  font-weight: 500;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid #2d2d3f;
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
  border-top: 1px solid #23232f;
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
  overflow-y: auto;
  overscroll-behavior: contain;
}

.modal-content {
  background: #23232f;
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
  border-bottom: 1px solid #23232f;
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
  overscroll-behavior: contain;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid #23232f;
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
  background: #2d2d3f;
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
  background: #121a2e;
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
    background: #23232f;
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
    background: #2a2a38;
  }

  .video-card-mobile .card-thumb-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 24px;
    color: #ccc;
    background: linear-gradient(135deg, #1a1a24 0%, #2d2d3f 100%);
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
    color: #c9d1d9;
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
    border-top: 1px solid #1a1a24;
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
    background: #23232f;
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
    color: #c9d1d9;
  }

  .mobile-selection-bar .select-all input {
    width: 18px;
    height: 18px;
    cursor: pointer;
  }

  .mobile-selection-bar .selected-count {
    flex: 1;
    font-size: 12px;
    color: #8b949e;
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

/* 资源库管理样式 */
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

/* ============ 资源库导入弹窗（文件夹/扫描/选择） ============ */
.detail-folders-section h4 {
  margin: 0 0 12px;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary, #e1e1e1);
}

.folder-tabs {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  padding: 4px 0;
}

.folder-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border: 1px solid var(--border-color, #2d2d3f);
  border-radius: 8px;
  background: var(--card-bg, #23232f);
  cursor: pointer;
  font-size: 13px;
  color: #8b949e;
  transition: all 0.2s;
  white-space: nowrap;
}

.folder-tab:hover {
  border-color: var(--primary, #1890ff);
  color: var(--primary, #1890ff);
  background: rgba(24, 144, 255, 0.04);
}

.folder-tab.active {
  background: var(--primary, #1890ff);
  color: #fff;
  border-color: var(--primary, #1890ff);
}

.folder-tab.active .tab-count {
  background: rgba(255, 255, 255, 0.3);
  color: #fff;
}

.tab-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 6px;
  border-radius: 10px;
  background: rgba(0, 0, 0, 0.06);
  font-size: 11px;
  font-weight: 600;
  color: #888;
}

@media (max-width: 768px) {

  .folder-tabs {

    overflow-x: auto;

    flex-wrap: nowrap;

    -webkit-overflow-scrolling: touch;

    padding-bottom: 4px;

  }

  .folder-tab {

    flex-shrink: 0;

  }

}



.import-config,

.scan-results,

.import-progress {

  background: #23232f;

  border-radius: 12px;

  padding: 24px;

  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);

}



.import-config h4,

.scan-results h4,

.import-progress h4 {

  margin: 0 0 20px 0;

  font-size: 18px;

  color: #e6edf3;

}



.input-group {

  display: flex;

  gap: 12px;

}



.folder-input {

  flex: 1;

  padding: 12px 16px;

  font-size: 14px;

  border: 2px solid #2d2d3f;

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

  color: #8b949e;

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

  background: #16161d;

  border-radius: 8px;

  margin-bottom: 16px;

}



.results-toolbar .select-all {

  font-weight: 600;

  color: #e6edf3;

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

  border: 1px solid #2d2d3f;

  border-radius: 8px;

}



.video-item {

  display: flex;

  align-items: center;

  gap: 12px;

  padding: 16px;

  border-bottom: 1px solid #23232f;

  cursor: pointer;

  transition: background-color 0.2s;

}



.video-item:last-child {

  border-bottom: none;

}



.video-item:hover:not(.existing) {

  background-color: #1a1a24;

}



.video-item.selected {

  background-color: #12243a;

  border-left: 4px solid #2196F3;

}



.video-item.existing {

  background-color: #1a1a24;

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

  color: #e6edf3;

  margin-bottom: 4px;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}



.video-meta {

  display: flex;

  gap: 16px;

  font-size: 12px;

  color: #8b949e;

}



.video-meta span {

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}



.import-actions {

  margin-top: 24px;

  padding-top: 24px;

  border-top: 1px solid #2d2d3f;

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

  background-color: #16241a;

}



.stat-item.warning {

  background-color: #2e2112;

}



.stat-item.error {

  background-color: #2e1212;

}



.stat-label {

  display: block;

  font-size: 14px;

  color: #8b949e;

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

  background-color: #2e1212;

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

  color: #8b949e;

}



.import-errors li {

  margin-bottom: 8px;

}



.card {

  background: #23232f;

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

  background: #2a2a38;

  border-radius: 8px;

  margin-bottom: 16px;

  font-size: 14px;

}



.path-label {

  color: #8b949e;

  margin-right: 8px;

}



.path-value {

  color: #e6edf3;

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

  border: 1px solid #2d2d3f;

  background: #23232f;

  border-radius: 6px;

  cursor: pointer;

  font-size: 14px;

  transition: all 0.2s;

}



.nav-btn:hover:not(:disabled) {

  background: #2a2a38;

  border-color: #2196F3;

}



.nav-btn:disabled {

  opacity: 0.5;

  cursor: not-allowed;

}



.folder-list-container {

  flex: 1;

  overflow-y: auto;

  border: 1px solid #2d2d3f;

  border-radius: 8px;

  min-height: 300px;

  max-height: 400px;

  overscroll-behavior: contain;

}

.new-folder-row {

  display: flex;

  gap: 8px;

  margin-bottom: 14px;

}

.new-folder-input {

  flex: 1;

  padding: 8px 12px;

  border: 1px solid #2d2d3f;

  border-radius: 6px;

  background: #1e1e28;

  color: #e6edf3;

  font-size: 14px;

}

.new-folder-input:focus {

  outline: none;

  border-color: #2196F3;

}



.loading-state {

  display: flex;

  flex-direction: column;

  align-items: center;

  justify-content: center;

  padding: 60px;

  color: #8b949e;

}



.loading-spinner {

  width: 40px;

  height: 40px;

  border: 3px solid #2d2d3f;

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

  background-color: #12243a;

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

  color: #e6edf3;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}



.folder-type {

  font-size: 12px;

  color: #8b949e;

  margin-top: 2px;

}



.folder-arrow {

  color: #999;

  font-size: 12px;

}



.library-card {

  background: #23232f;

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

  color: #8b949e;

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

  background: #2a2a38;

  border-top: 1px solid #2d2d3f;

}



.library-card-actions .action-btn {

  flex: 1;

  padding: 6px 12px;

  font-size: 12px;

}



/* 文件夹管理样式 */

.folder-form {

  margin-bottom: 24px;

  padding: 16px;

}



.folder-form h4 {

  margin: 0 0 16px 0;

  color: #c9d1d9;

}



.input-with-button {

  display: flex;

  gap: 8px;

}



.input-with-button input {

  flex: 1;

}



.folder-item-file {

  opacity: 0.85;

}



.folder-item-file:hover {

  background: #12243a;

}



.folder-list-section h4 {

  margin: 0 0 16px 0;

  color: #c9d1d9;

}



.folder-items {

  display: flex;

  flex-direction: column;

  gap: 12px;

}



.folder-item {

  display: flex;

  justify-content: space-between;

  align-items: center;

  padding: 12px 16px;

  gap: 16px;

}



.folder-info {

  flex: 1;

  min-width: 0;

}



.folder-name {

  font-weight: 500;

  color: #c9d1d9;

  margin-bottom: 4px;

  word-break: break-all;

}



.folder-type-icon {

  margin-right: 4px;

}



.default-badge {

  display: inline-block;

  background: #4caf50;

  color: white;

  font-size: 11px;

  padding: 2px 6px;

  border-radius: 4px;

  margin-right: 8px;

}



.folder-path {

  color: #8b949e;

  font-size: 13px;

  word-break: break-all;

  margin-bottom: 4px;

}



.folder-meta {

  font-size: 12px;

  color: #999;

}



.folder-meta span {

  margin-right: 16px;

}



.folder-actions {

  display: flex;

  gap: 8px;

  flex-shrink: 0;

}



/* 权限配置样式 */

.modal-large {

  max-width: 800px;

}



.permission-form {

  margin-bottom: 24px;

  padding-bottom: 24px;

  border-bottom: 1px solid #2d2d3f;

}



.permission-form h4,

.permission-list h4 {

  margin: 0 0 16px 0;

  font-size: 16px;

  color: #c9d1d9;

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



/* 资源库弹窗样式 */

.library-modal {

  max-width: 520px;

}



.library-modal .modal-header h3 {

  font-size: 20px;

  color: #c9d1d9;

}



.library-modal .form-group {

  margin-bottom: 20px;

}



.library-modal label {

  display: block;

  font-size: 15px;

  font-weight: 500;

  color: #c9d1d9;

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

  border: 2px solid #2d2d3f;

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

  color: #8b949e;

}



.form-tip {

  display: flex;

  align-items: center;

  gap: 8px;

  padding: 12px 16px;

  background: #16161d;

  border-radius: 8px;

  font-size: 14px;

  color: #8b949e;

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

  background: #2a2a38;

  color: #8b949e;

}



.btn-secondary:hover {

  background: #2d2d3f;

}



/* ============ 系统日志样式 ============ */



.log-type-tabs {

  display: flex;

  gap: 8px;

  margin-bottom: 16px;

  flex-wrap: wrap;

}



.log-type-btn {

  padding: 6px 14px;

  border: 1px solid #2d2d3f;

  border-radius: 6px;

  background: #23232f;

  cursor: pointer;

  font-size: 13px;

  transition: all 0.2s;

}



.log-type-btn:hover {

  background: #2a2a38;

}



.log-type-btn.active {

  background: #1976D2;

  color: #fff;

  border-color: #1976D2;

}



/* 服务筛选样式 */

.log-service-filter {

  display: flex;

  align-items: center;

  gap: 8px;

  margin-bottom: 16px;

  flex-wrap: wrap;

}



.log-service-filter .filter-label {

  font-size: 13px;

  color: #8b949e;

  font-weight: 500;

}



.log-service-filter .service-select {

  padding: 6px 12px;

  border: 1px solid #2d2d3f;

  border-radius: 6px;

  background: #23232f;

  font-size: 13px;

  cursor: pointer;

  min-width: 150px;

}



.log-service-filter .service-select:focus {

  outline: none;

  border-color: #1976D2;

}



.log-container {

  background: #23232f;

  border-radius: 8px;

  border: 1px solid #2d2d3f;

  overflow: visible;

  color: #c9d1d9;

  display: flex;

  flex-direction: column;

  flex: 1;

  min-height: 500px;

}



.log-table-wrapper {

  overflow-x: auto;

  overflow-y: auto;

  max-height: calc(100vh - 340px);

  flex: 1;

}



.log-table {

  width: 100%;

  border-collapse: collapse;

  font-size: 13px;

  color: #c9d1d9;

}



.log-table th {

  background: #2a2a38;

  padding: 10px 12px;

  text-align: left;

  font-weight: 600;

  border-bottom: 2px solid #2d2d3f;

  white-space: nowrap;

  color: #c9d1d9;

}



.log-table td {

  padding: 8px 12px;

  border-bottom: 1px solid #23232f;

  vertical-align: top;

  color: #c9d1d9;

}



.log-table tr:hover {

  background: #1a1a24;

}



.log-col-time {

  width: 150px;

  white-space: nowrap;

  color: #8b949e;

}



.log-col-level {

  width: 90px;

  white-space: nowrap;

}



.log-col-module {

  width: 220px;

  white-space: nowrap;

  color: #8b949e;

}



.log-col-content {

  word-break: break-all;

  min-width: 200px;

  color: #c9d1d9;

}



.log-mono {

  font-family: 'Cascadia Code', 'Fira Code', 'Consolas', monospace;

  font-size: 12px;

}



/* 日志等级徽标 */

.log-badge {

  display: inline-block;

  padding: 2px 8px;

  border-radius: 4px;

  font-size: 11px;

  font-weight: 600;

}



.log-level-info { background: #2196F3; color: #fff; }

.log-level-warn { background: #FF9800; color: #fff; }

.log-level-error { background: #f44336; color: #fff; }

.log-level-fatal { background: #B71C1C; color: #fff; }

.log-level-debug { background: #9E9E9E; color: #fff; }



.log-source {

  color: #8b949e;

  font-size: 12px;

  font-family: monospace;

}



/* 分页 */

.log-pagination {

  display: flex;

  align-items: center;

  justify-content: space-between;

  padding: 12px 16px;

  border-top: 1px solid #2d2d3f;

  flex-wrap: wrap;

  gap: 8px;

}



.log-page-info {

  color: #8b949e;

  font-size: 13px;

}



.log-page-btns {

  display: flex;

  align-items: center;

  gap: 6px;

}



.page-btn {

  padding: 4px 10px;

  border: 1px solid #2d2d3f;

  border-radius: 4px;

  background: #23232f;

  cursor: pointer;

  font-size: 12px;

}



.page-btn:hover:not(:disabled) {

  background: #2a2a38;

}



.page-btn:disabled {

  opacity: 0.4;

  cursor: not-allowed;

}



.page-current {

  font-size: 13px;

  padding: 0 8px;

  color: #c9d1d9;

}



.page-size-select {

  padding: 4px 8px;

  border: 1px solid #2d2d3f;

  border-radius: 4px;

  font-size: 12px;

  cursor: pointer;

}



/* 加载和空状态 */

.loading-text, .empty-text {

  text-align: center;

  padding: 40px;

  color: #999;

}



/* 移动端卡片 */

.log-cards {

  display: none;

}



/* 移动端适配 */

@media (max-width: 768px) {

  .log-table-wrapper {

    display: none;

  }



  .log-cards {

    display: block;

  }



  .log-container {

    overflow-y: auto;

    max-height: calc(100vh - 350px);

    -webkit-overflow-scrolling: touch;

    min-height: 300px;

  }



  .tab-content {

    min-height: auto;

  }



  .log-card {

    border-bottom: 1px solid #23232f;

    padding: 12px;

  }



  .log-card:last-child {

    border-bottom: none;

  }



  .log-card-header {

    display: flex;

    align-items: center;

    gap: 8px;

    margin-bottom: 6px;

  }



  .log-card-module {

    font-size: 11px;

    color: #888;

  }



  .log-card-content {

    font-size: 13px;

    color: #c9d1d9;

    word-break: break-all;

    margin-bottom: 6px;

  }



  .log-card-time {

    font-size: 11px;

    color: #999;

  }



  .log-pagination {

    flex-direction: column;

    align-items: stretch;

    text-align: center;

  }



  .log-page-btns {

    justify-content: center;

  }

}



/* ============ 系统监控样式 ============ */

.monitor-overview {

  display: grid;

  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));

  gap: 16px;

  margin-bottom: 24px;

}



.monitor-card {

  background: #23232f;

  border-radius: 12px;

  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);

  overflow: hidden;

}



.monitor-card-header {

  display: flex;

  align-items: center;

  gap: 10px;

  padding: 16px 20px;

  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);

  color: white;

}



.monitor-icon {

  font-size: 20px;

}



.monitor-title {

  font-size: 15px;

  font-weight: 600;

}



.monitor-card-body {

  padding: 20px;

}



.monitor-value {

  font-size: 36px;

  font-weight: 700;

  margin-bottom: 12px;

}



.monitor-value.normal { color: #22c55e; }

.monitor-value.warning { color: #f59e0b; }

.monitor-value.danger { color: #ef4444; }



.monitor-bar-container {

  height: 8px;

  background: #2d2d3f;

  border-radius: 4px;

  overflow: hidden;

  margin-bottom: 12px;

}



.monitor-bar-container.small {

  height: 4px;

  flex: 1;

}



.monitor-bar {

  height: 100%;

  border-radius: 4px;

  transition: width 0.3s ease;

}



.monitor-bar.normal { background: linear-gradient(90deg, #22c55e, #4ade80); }

.monitor-bar.warning { background: linear-gradient(90deg, #f59e0b, #fbbf24); }

.monitor-bar.danger { background: linear-gradient(90deg, #ef4444, #f87171); }



.monitor-detail {

  display: flex;

  justify-content: space-between;

  font-size: 13px;

  color: #8b949e;

  margin-bottom: 6px;

}



.monitor-detail:last-child {

  margin-bottom: 0;

}



.fs-type {

  color: #888;

  font-size: 12px;

}



.core-usage {

  margin-top: 16px;

  border-top: 1px solid #2d2d3f;

  padding-top: 12px;

}



.core-usage-item {

  display: flex;

  align-items: center;

  gap: 8px;

  margin-bottom: 8px;

}



.core-usage-item:last-child {

  margin-bottom: 0;

}



.core-label {

  font-size: 11px;

  color: #888;

  width: 45px;

}



.core-value {

  font-size: 11px;

  color: #8b949e;

  width: 40px;

  text-align: right;

}



.monitor-uptime {

  display: flex;

  align-items: center;

  gap: 8px;

  padding: 12px 16px;

  background: #16161d;

  border-radius: 8px;

  font-size: 14px;

}



.uptime-label {

  color: #8b949e;

}



.uptime-value {

  color: #c9d1d9;

  font-weight: 500;

}



/* 移动端适配 */

@media (max-width: 768px) {

  .monitor-overview {

    grid-template-columns: 1fr;

  }

}



/* ============ 缩略图管理样式 ============ */

.thumb-stats-grid {

  display: grid;

  grid-template-columns: repeat(4, 1fr);

  gap: 16px;

  margin-bottom: 24px;

}



.thumb-stat-card {

  background: var(--card-bg, #1e1e2e);

  border-radius: 12px;

  padding: 20px;

  display: flex;

  align-items: center;

  gap: 16px;

  border: 1px solid var(--border-color, #2d2d3f);

  transition: all 0.2s;

}



.thumb-stat-card:hover {

  transform: translateY(-1px);

  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);

}



.thumb-stat-card.stat-warning {

  border-color: #f59e0b;

  background: linear-gradient(135deg, rgba(245, 158, 11, 0.08) 0%, var(--card-bg, #1e1e2e) 100%);

}



.stat-icon {

  font-size: 28px;

  line-height: 1;

}



.stat-info {

  display: flex;

  flex-direction: column;

}



.stat-value {

  font-size: 24px;

  font-weight: 700;

  color: var(--text-primary, #e1e1e1);

}



.stat-label {

  font-size: 13px;

  color: var(--text-secondary, #888);

  margin-top: 2px;

}



.status-ok {

  color: #10b981;

}



.status-error {

  color: #ef4444;

}



.status-unknown {

  color: #888;

}



.text-error {

  color: #ef4444;

}



.thumb-service-detail {

  background: var(--card-bg, #1e1e2e);

  border-radius: 12px;

  padding: 16px 20px;

  margin-bottom: 24px;

  border: 1px solid var(--border-color, #2d2d3f);

}



.thumb-service-detail h4 {

  margin: 0 0 12px;

  font-size: 15px;

  color: var(--text-secondary, #888);

}



.task-stats-row {

  display: flex;

  gap: 24px;

  font-size: 14px;

  color: var(--text-primary, #e1e1e1);

}



.task-stats-row span b {

  font-weight: 600;

}



.thumb-config-form {

  margin-top: 8px;

}



.config-section-title {

  font-size: 16px;

  font-weight: 600;

  margin: 0 0 20px;

  color: var(--text-primary, #e1e1e1);

  padding-bottom: 12px;

  border-bottom: 1px solid var(--border-color, #2d2d3f);

}



.form-row {

  display: flex;

  justify-content: space-between;

  align-items: center;

}



.form-label-area {

  display: flex;

  flex-direction: column;

}



.form-label-area label {

  font-weight: 500;

  color: var(--text-primary, #e1e1e1);

}



.form-hint {

  font-size: 12px;

  color: var(--text-secondary, #888);

  margin-top: 4px;

}



.input-with-hint {

  display: flex;

  flex-direction: column;

  gap: 4px;

}



.input-with-hint input {

  width: 180px;

}



.input-hint {

  font-size: 12px;

  color: var(--text-secondary, #888);

}



.auto-status-banner {

  display: flex;

  align-items: center;

  gap: 10px;

  padding: 12px 16px;

  border-radius: 8px;

  margin: 16px 0;

  font-size: 14px;

  font-weight: 500;

}



.auto-status-banner.running {

  background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(16, 185, 129, 0.05) 100%);

  border: 1px solid rgba(16, 185, 129, 0.3);

  color: #10b981;

}



.auto-status-dot {

  width: 8px;

  height: 8px;

  border-radius: 50%;

  background: #10b981;

  animation: pulse-dot 1.5s infinite;

}



@keyframes pulse-dot {

  0%, 100% { opacity: 1; }

  50% { opacity: 0.4; }

}



.auto-status-banner .action-btn.small {

  margin-left: auto;

  padding: 4px 12px;

  font-size: 13px;

}



.badge-count {

  display: inline-flex;

  align-items: center;

  justify-content: center;

  min-width: 20px;

  height: 20px;

  padding: 0 6px;

  border-radius: 10px;

  background: rgba(255, 255, 255, 0.2);

  font-size: 11px;

  font-weight: 600;

  margin-left: 8px;

}



.loading-placeholder {

  display: flex;

  flex-direction: column;

  align-items: center;

  justify-content: center;

  padding: 60px;

  color: var(--text-secondary, #888);

}



.loading-spinner {

  width: 32px;

  height: 32px;

  border: 3px solid var(--border-color, #2d2d3f);

  border-top-color: #667eea;

  border-radius: 50%;

  animation: spin 0.8s linear infinite;

  margin-bottom: 12px;

}



@keyframes spin {

  to { transform: rotate(360deg); }

}



/* 移动端适配 */

@media (max-width: 768px) {

  .thumb-stats-grid {

    grid-template-columns: repeat(2, 1fr);

    gap: 12px;

  }

  

  .thumb-stat-card {

    padding: 14px;

  }

  

  .stat-value {

    font-size: 20px;

  }

  

  .form-row {

    flex-direction: column;

    align-items: flex-start;

    gap: 10px;

  }

  

  .task-stats-row {

    flex-wrap: wrap;

    gap: 12px;

  }

  

  .input-with-hint input {

    width: 100%;

  }

}



/* ============ 服务管理样式 ============ */

.services-list {

  display: flex;

  flex-direction: column;

  gap: 16px;

}



.service-card {

  background: var(--card-bg, #1e1e2e);

  border-radius: 12px;

  border: 1px solid var(--border-color, #2d2d3f);

  overflow: hidden;

  transition: all 0.2s;

}



.service-card:hover {

  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);

}



.service-card.svc-card-operating {

  border-color: rgba(102, 126, 234, 0.4);

  opacity: 0.9;

}



.svc-header {

  display: flex;

  justify-content: space-between;

  align-items: center;

  padding: 16px 20px;

  border-bottom: 1px solid var(--border-color, #2d2d3f);

}



.svc-title-area {

  display: flex;

  align-items: center;

  gap: 10px;

}



.svc-title-area h4 {

  margin: 0;

  font-size: 16px;

  font-weight: 600;

  color: var(--text-primary, #e1e1e1);

}



.svc-name-tag {

  font-size: 11px;

  padding: 2px 8px;

  border-radius: 4px;

  background: rgba(102, 126, 234, 0.15);

  color: #667eea;

  font-family: monospace;

  font-weight: 500;

}



.svc-status-lights {

  display: flex;

  gap: 16px;

}



.health-light {

  display: flex;

  align-items: center;

  gap: 6px;

  padding: 4px 10px;

  border-radius: 6px;

  font-size: 12px;

  font-weight: 500;

}



.light-dot {

  width: 10px;

  height: 10px;

  border-radius: 50%;

  display: inline-block;

}



.light-label {

  color: var(--text-secondary, #888);

}



/* 状态颜色 */

.health-light.svc-running .light-dot {

  background: #10b981;

  box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);

}

.health-light.svc-stopped .light-dot {

  background: #ef4444;

  box-shadow: 0 0 6px rgba(239, 68, 68, 0.5);

}

.health-light.svc-paused .light-dot {

  background: #f59e0b;

  box-shadow: 0 0 6px rgba(245, 158, 11, 0.5);

}

.health-light.svc-pending .light-dot {

  background: #3b82f6;

  box-shadow: 0 0 6px rgba(59, 130, 246, 0.5);

  animation: pulse-dot 1s infinite;

}

.health-light.svc-unknown .light-dot {

  background: #8b949e;

}



.svc-details {

  padding: 16px 20px;

}



.svc-desc {

  font-size: 13px;

  color: var(--text-secondary, #888);

  margin-bottom: 12px;

}



.svc-metrics {

  display: flex;

  flex-wrap: wrap;

  gap: 16px;

}



.metric-item {

  display: flex;

  flex-direction: column;

  gap: 2px;

  min-width: 80px;

}



.metric-label {

  font-size: 11px;

  color: var(--text-secondary, #888);

  text-transform: uppercase;

  letter-spacing: 0.5px;

}



.metric-value {

  font-size: 14px;

  font-weight: 600;

  color: var(--text-primary, #e1e1e1);

  display: flex;

  align-items: center;

  gap: 4px;

}



.metric-value.mono {

  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;

  font-size: 13px;

}



.metric-value.svc-running { color: #10b981; }

.metric-value.svc-stopped { color: #ef4444; }

.metric-value.svc-paused { color: #f59e0b; }

.metric-value.svc-pending { color: #3b82f6; }

.metric-value.svc-unknown { color: #888; }



.svc-health-detail {

  margin-top: 8px;

  font-size: 12px;

  color: var(--text-secondary, #888);

  padding: 4px 8px;

  background: rgba(255, 255, 255, 0.03);

  border-radius: 4px;

}



.svc-actions {

  padding: 12px 20px;

  border-top: 1px solid var(--border-color, #2d2d3f);

  display: flex;

  gap: 10px;

  justify-content: flex-end;

}



.svc-operating-indicator {

  display: flex;

  align-items: center;

  gap: 8px;

  color: #3b82f6;

  font-size: 13px;

  font-weight: 500;

  width: 100%;

  justify-content: center;

}



.loading-spinner.small {

  width: 16px;

  height: 16px;

  border-width: 2px;

  margin-bottom: 0;

}



.auto-refresh-hint {

  font-size: 12px;

  color: var(--text-secondary, #888);

  display: flex;

  align-items: center;

  gap: 4px;

}



.auto-refresh-hint::before {

  content: '';

  display: inline-block;

  width: 8px;

  height: 8px;

  border-radius: 50%;

  background: #10b981;

  animation: pulse-dot 2s infinite;

}



.empty-state {

  text-align: center;

  padding: 60px;

  color: var(--text-secondary, #888);

}



/* 移动端服务卡片适配 */

@media (max-width: 768px) {

  .svc-header {

    flex-direction: column;

    align-items: flex-start;

    gap: 10px;

  }



  .svc-metrics {

    gap: 10px;

  }



  .metric-item {

    min-width: 60px;

  }



  .svc-actions {

    justify-content: center;

  }

}







/* 资源库导入弹窗（重设计：替代原向下展开 + 独立批量导入Tab） */

.import-modal { max-width: 960px; width: 95%; display: flex; flex-direction: column; max-height: 90vh; }

.import-modal-header { display: flex; justify-content: space-between; align-items: flex-start; }

.import-modal-title h3 { margin: 0; }

.import-modal-title .modal-subtitle { margin: 4px 0 0; color: #888; font-size: 13px; }

.import-modal-body { overflow-y: auto; padding: 16px 20px; }

.import-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }

.scan-progress-inline { color: #8b949e; font-size: 13px; }

.import-results { padding: 0; }

.import-video-list { max-height: 46vh; overflow-y: auto; border: 1px solid #23232f; border-radius: 8px; }

.import-progress-inline { padding: 10px 0; color: #8b949e; font-size: 13px; }

.import-action-bar { display: flex; align-items: center; gap: 14px; border-top: 1px solid #333; padding: 14px 20px; background: #23232f; }

.import-action-bar .selected-count { color: #8b949e; font-size: 13px; }

.import-action-bar .action-btn.primary.large { margin-left: auto; }

</style>

