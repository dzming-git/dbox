<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/userStore'
import { api } from '../api'
import { videoApi, libraryApi } from '../api'
import { configApi } from '../api'
import { thumbnailManageApi } from '../api'
import { serviceManageApi, systemApi } from '../api'
import { resourceApi } from '../api'
import { trashApi } from '../api'
import {
  formatDate,
  formatPath,
  formatFileSize
} from '../utils/adminCommon'
import { useToast } from '../composables/useToast'
import { withThumbToken } from '../utils/media'
import AdminLogs from '../admin/AdminLogs.vue'
import AdminMonitor from '../admin/AdminMonitor.vue'
import AdminConfig from '../admin/AdminConfig.vue'
import AdminUsers from '../admin/AdminUsers.vue'
import Pagination from '../components/Pagination.vue'

const userStore = useUserStore()
const router = useRouter()
// 仅资源库管理员（非全局管理员）：只开放资源库管理，隐藏其它管理标签页
const isResourceAdminOnly = computed(() => userStore.canManageResources && !userStore.isAdmin)
const { toastMessage, showToastFlag, showToast } = useToast()

// 当前活动标签页 —— 使用 sessionStorage 持久化，防止手机切后台后状态丢失
const ADMIN_TAB_KEY = 'admin_active_tab'
const VALID_ADMIN_TABS = ['dashboard', 'services', 'thumbnail', 'libraries', 'resources', 'logs', 'users', 'monitor', 'config']
const _savedTab = sessionStorage.getItem(ADMIN_TAB_KEY)
const activeTab = ref(VALID_ADMIN_TABS.includes(_savedTab) ? _savedTab : 'dashboard')

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
  videos: false,
  users: false,
  libraries: false
})

// 视频管理
const videos = ref<any[]>([])
const videoSearch = ref('')
const videoPage = ref(1)
const videoTotal = ref(0)
const VIDEO_PAGE_SIZE = 20
const videoTotalPages = computed(() => Math.ceil(videoTotal.value / VIDEO_PAGE_SIZE) || 1)
const videoPageRange = computed(() => {
  const cur = videoPage.value
  const total = videoTotalPages.value
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
const resourceLibraryFilter = ref<number | ''>('')  // 当前筛选的资源库ID，空字符串表示全部
const selectedVideos = ref<string[]>([])
const editingVideo = ref<any>(null)
const editingVideoTags = ref<string>('')  // 标签输入（用 "/" 分隔）
const showVideoEditModal = ref(false)
// 排序选项（不使用推荐）
const sortOptions = [
  { value: 'name', label: '视频名' },
  { value: 'created_at', label: '文件时间' },
  { value: 'view_count', label: '播放量' },
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
  is_auto_generating: false,
  auto_generate_progress: null
})

// 自动生成实时进度
const thumbProgress = ref<any>(null)
let autoProgressTimer: number | null = null

const thumbProgressPercent = computed(() => {
  const p = thumbProgress.value
  if (!p || !p.total) return 0
  return Math.min(100, Math.round((p.processed / p.total) * 100))
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
const resourceViewer = ref({
  open: false,
  libId: null as number | null,
  libName: '',
  activeType: 'video',
  types: [
    { key: 'video', label: '视频', count: 0 },
    { key: 'gallery', label: '图集', count: 0 },
    { key: 'post', label: '帖子', count: 0 },
    { key: 'text', label: '文本', count: 0 },
  ],
  items: [] as any[],
  loading: false,
})
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
  role: 'hidden',
  access_level: 'read',
  permissions: [] as string[]
})

// 资源库自动扫描开关（独立于全局/资源库管理员的可见性权限）
const scanConfig = ref({
  library_watch_enabled: true,   // 文件夹实时监控（文件增删改实时同步）
  auto_scan_on_startup: true     // 服务启动时全量扫描磁盘
})
const scanConfigLoaded = ref(false)
const scanSaving = ref(false)
const scanSaved = ref(false)

const loadScanConfig = async () => {
  try {
    const cfg = await configApi.getConfig() as any
    scanConfig.value = {
      library_watch_enabled: !!cfg.library_watch_enabled,
      auto_scan_on_startup: !!cfg.auto_scan_on_startup
    }
  } catch (e) {
    console.error('加载扫描配置失败:', e)
  } finally {
    scanConfigLoaded.value = true
  }
}

const saveScanConfig = async () => {
  scanSaving.value = true
  try {
    await configApi.updateConfig({
      library_watch_enabled: scanConfig.value.library_watch_enabled,
      auto_scan_on_startup: scanConfig.value.auto_scan_on_startup
    } as any)
    scanSaved.value = true
    showToast('扫描设置已保存，实时监控已立即生效')
  } catch (e) {
    showToast('保存失败：' + (e instanceof Error ? e.message : String(e)))
  } finally {
    scanSaving.value = false
  }
}

// 文件夹管理
const libraryFolders = ref<any[]>([])
const showFolderModal = ref(false)
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

// 一键同步全部资源库（增量/校验/全量，覆盖软件未运行或旧逻辑漏更新的情况）
const scanAllScanning = ref(false)
const scanAllMessage = ref('')
const scanAllMode = ref('incremental')
let scanAllTimer: any = null

const scanAllLibraries = async (mode: 'incremental' | 'verify' | 'full' = 'incremental') => {
  try {
    scanAllMode.value = mode
    const res = await libraryApi.scanAllLibraries({ mode }) as any
    if (res.success) {
      scanAllScanning.value = true
      const label = mode === 'incremental' ? '增量同步' : mode === 'verify' ? '校验清理' : '全量重建'
      scanAllMessage.value = `${label}已启动...`
      pollScanAll()
    } else {
      showToast(res.message || '启动失败')
    }
  } catch (e: any) {
    console.error('启动同步失败:', e)
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
          showToast(res.message || '同步完成')
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
// 封面加载失败的资源（资源索引被删除目录等非致命问题）标记为破图，改用占位图标
const coverBroken = ref<Set<string>>(new Set())
const coverKey = (r: any) => `${r.type}:${r.id}`
const isCoverBroken = (r: any) => coverBroken.value.has(coverKey(r))
const onCoverError = (r: any) => {
  const k = coverKey(r)
  if (!coverBroken.value.has(k)) {
    const s = new Set(coverBroken.value)
    s.add(k)
    coverBroken.value = s
  }
}

const resourceTotalPages = computed(() => Math.ceil(resourceTotal.value / RESOURCE_PAGE_SIZE) || 1)

const resourcePageRange = computed(() => {
  const cur = resourcePage.value
  const total = resourceTotalPages.value
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

const openResourceViewer = (lib: any) => {
  resourceViewer.value.libId = lib.id
  resourceViewer.value.libName = lib.name
  resourceViewer.value.activeType = 'video'
  resourceViewer.value.types = [
    { key: 'video', label: '视频', count: lib.video_count || 0 },
    { key: 'gallery', label: '图集', count: lib.gallery_count || 0 },
    { key: 'post', label: '帖子', count: lib.post_count || 0 },
    { key: 'text', label: '文本', count: lib.text_count || 0 },
  ]
  resourceViewer.value.open = true
  loadLibraryResources()
}

const closeResourceViewer = () => {
  resourceViewer.value.open = false
  resourceViewer.value.libId = null
  resourceViewer.value.items = []
}

const loadLibraryResources = async () => {
  const rv = resourceViewer.value
  if (rv.libId == null) return
  rv.loading = true
  try {
    const params: any = { rtype: rv.activeType, library_id: rv.libId, limit: 200, show_hidden: 'true' }
    const res = await api.get('/api/admin/resources', { params }) as any
    if (res.success) {
      rv.items = res.items || []
    } else {
      rv.items = []
    }
  } catch (e) {
    console.error('加载库资源失败:', e)
    rv.items = []
  } finally {
    rv.loading = false
  }
}

const editResourceFromViewer = (item: any) => {
  editResource(item)
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
    // 后端成功即返回 2xx（axios 非 2xx 会抛异常进入 catch）；
    // 响应体为 resource_index.to_dict()（含 hidden 字段，无 success 包裹），故直接读取 res.hidden。
    const res: any = await resourceApi.setHidden(rid, !item.hidden) as any
    const updated = res && typeof res.hidden === 'boolean' ? res.hidden : !item.hidden
    item.hidden = updated
    showToast(updated ? '已隐藏' : '已显示')
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

// 获取系统统计（视频/标签/用户总数）
const fetchSystemStats = async () => {
  loading.value.stats = true
  try {
    const res = await api.get('/api/stats/overview') as any
    if (res && res.success) {
      systemStats.value = {
        videos: res.total || 0,
        tags: res.total_tags || 0,
        users: res.total_users || 0,
      }
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
      // 同步进度快照
      thumbProgress.value = res.stats?.auto_generate_progress || null
      startAutoProgressPolling()
    }
  } catch (error) {
    console.error('获取缩略图配置失败:', error)
  } finally {
    thumbLoading.value = false
  }
}

// 自动生成进度轮询
const pollAutoProgress = async () => {
  try {
    const res = await thumbnailManageApi.getAutoStatus() as any
    if (res.success && res.progress) {
      thumbProgress.value = res.progress
      // 实时同步缺失数量卡片：缩略图生成后磁盘文件增加，缺失数应随之下降
      if (typeof res.no_thumbnail_count === 'number' && thumbStats.value) {
        thumbStats.value = { ...thumbStats.value, no_thumbnail_count: res.no_thumbnail_count }
      }
      // 进度是否仍在推进：以 thumbnaild 真实待处理数（pending）为准，
      // 不再依赖 web 端 running 标志（后端线程可能已退出但 thumbnaild 仍在执行）。
      const pending = res.progress.pending ?? (res.progress.total - res.progress.processed)
      const stillGoing = res.is_running || (pending > 0 && res.progress.total > 0)
      if (!stillGoing) {
        // 真正结束后刷新统计并停止轮询
        if (autoProgressTimer) {
          clearInterval(autoProgressTimer)
          autoProgressTimer = null
        }
        fetchThumbnailConfig()
      }
    }
  } catch (error) {
    // 忽略轮询错误
  }
}

const startAutoProgressPolling = () => {
  if (autoProgressTimer) clearInterval(autoProgressTimer)
  // 只要已开启自动生成、或已有进度/待处理任务，就启动轮询
  const p = thumbProgress.value
  if (thumbConfig.value.auto_generate || (p && (p.total > 0 || p.running || (p.pending ?? 0) > 0))) {
    autoProgressTimer = window.setInterval(pollAutoProgress, 2000)
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

// ============ 总体健康灯（看门狗） ============
// 由 com.dbox.watchdog 汇总的整体健康状态：healthy / degraded / critical / unknown
const overallHealth = ref<string>('unknown')
const healthAlerts = ref<any[]>([])
const healthSource = ref<string>('')
let healthInterval: number | null = null

const fetchOverallHealth = async () => {
  try {
    const res = await systemApi.getHealth() as any
    if (res && res.success) {
      overallHealth.value = res.overall_status || 'unknown'
      healthAlerts.value = res.alerts || []
      healthSource.value = res.source || ''
    } else {
      overallHealth.value = 'unknown'
    }
  } catch (error) {
    console.error('获取总体健康状态失败:', error)
    overallHealth.value = 'unknown'
  }
}

const overallHealthClass = computed(() => {
  switch (overallHealth.value) {
    case 'healthy': return 'svc-running'
    case 'degraded': return 'svc-pending'
    case 'critical': return 'svc-stopped'
    default: return 'svc-unknown'
  }
})

const overallHealthText = computed(() => {
  switch (overallHealth.value) {
    case 'healthy': return '全部服务正常'
    case 'degraded': return '部分服务异常'
    case 'critical': return '存在严重告警'
    default: return '健康状态未知'
  }
})

const startHealthPolling = () => {
  if (healthInterval) return
  fetchOverallHealth()
  healthInterval = window.setInterval(fetchOverallHealth, 10000)
}

const stopHealthPolling = () => {
  if (healthInterval) {
    clearInterval(healthInterval)
    healthInterval = null
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

const isOperating = (serviceName: string) => {
  const s = serviceControlLoading.value === serviceName
  const svc = services.value.find(sv => sv.service_name === serviceName)
  // 操作中：显式 loading 或状态处于 PENDING
  const pending = svc && svc.system_status.includes('PENDING')
  return s || pending
}

// 停止/重启二次确认，防止误触
const showServiceConfirm = ref(false)
const serviceConfirmName = ref('')
const serviceConfirmAction = ref<'stop' | 'restart'>('stop')

const openServiceControlConfirm = (svc: any, action: 'stop' | 'restart') => {
  serviceConfirmName.value = svc.service_name
  serviceConfirmAction.value = action
  showServiceConfirm.value = true
}

const confirmServiceControl = () => {
  const name = serviceConfirmName.value
  const action = serviceConfirmAction.value
  showServiceConfirm.value = false
  controlService(name, action)
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
      description: editingVideo.value.description
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
    const res = await trashApi.getTrash()
    if (res.success) {
      trashItems.value = res.items || []
    } else {
      showToast(res.data.message || '加载回收站失败')
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || '加载回收站失败')
  } finally {
    trashLoading.value = false
  }
}

const restoreTrashItem = async (item: any) => {
  try {
    const res = await trashApi.restoreTrash(item.type, item.hash)
    if (res.success) {
      showToast('已恢复')
      loadTrash()
    } else {
      showToast(res.data.message || '恢复失败')
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || '恢复失败')
  }
}

const purgeTrashItem = async (item: any) => {
  if (!window.confirm(`确定要永久删除「${item.title}」吗？此操作不可恢复。`)) return
  try {
    const res = await trashApi.purgeTrash(item.type, item.hash)
    if (res.success) {
      showToast('已永久删除')
      loadTrash()
    } else {
      showToast(res.data.message || '删除失败')
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || '删除失败')
  }
}

const emptyTrash = async () => {
  if (trashItems.value.length === 0) return
  if (!window.confirm('确定要清空回收站吗？所有资源将被永久删除，不可恢复。')) return
  try {
    const res = await trashApi.emptyTrash()
    if (res.success) {
      showToast(res.message || '已清空回收站')
      loadTrash()
    } else {
      showToast(res.data.message || '清空失败')
    }
  } catch (e: any) {
    showToast(e?.response?.data?.message || '清空失败')
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
  if (bytes === null || bytes === undefined || isNaN(Number(bytes)) || Number(bytes) <= 0) return '-'
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

// 作者开源仓库
const repoUrl = 'https://github.com/dzming-git/dbox'

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
  // 支持通过 URL query 参数直接跳转到指定标签页（如 /admin?tab=services）
  // 注意：外部脚本入口已移至用户头像下拉菜单，不再作为后台标签页
  const routeTab = router.currentRoute.value.query?.tab as string
  const validTabs = ['services', 'thumbnail', 'libraries', 'resources', 'logs', 'users', 'monitor', 'config']
  if (routeTab && validTabs.includes(routeTab)) activeTab.value = routeTab

  fetchSystemInfo()
  fetchSystemStats()
  fetchSystemPaths()
  loadHotStats()
  loadScanConfig()  // 加载自动扫描开关配置（始终加载，不依赖标签页）
  startHealthPolling()  // 总体健康灯轮询（看门狗）
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
  stopHealthPolling()
  if (autoProgressTimer) {
    clearInterval(autoProgressTimer)
    autoProgressTimer = null
  }
})
</script>

<template>
  <div class="admin-page">
    <div class="admin-header">
      <h1>管理后台</h1>
      <div class="header-health">
        <div
          class="health-light overall-health"
          :class="overallHealthClass"
          :title="overallHealthText + (healthAlerts.length ? '（' + healthAlerts.length + ' 条告警）' : '') + (healthSource ? ' · 数据来源: ' + healthSource : '')"
        >
          <span class="light-dot"></span>
          <span class="light-label">{{ overallHealthText }}</span>
          <span v-if="healthAlerts.length" class="alert-badge">{{ healthAlerts.length }}</span>
        </div>
      </div>
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
          v-if="userStore.isAdmin || userStore.canManageResources"
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
          v-if="userStore.isAdmin"
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
      </div>

      <div class="tab-group">
        <span class="tab-group-label">账号</span>
        <button
          class="tab-btn"
          :class="{ active: activeTab === 'users' }"
          @click="switchTab('users')"
          v-if="userStore.isAdmin"
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
          <div v-else-if="trashItems.length === 0" class="empty-state trash-empty">
            <svg width="96" height="96" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M3 6h18" />
              <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
              <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
              <path d="M10 11v6" />
              <path d="M14 11v6" />
            </svg>
            <p>回收站为空</p>
            <p class="empty-sub">已删除的资源会出现在这里，可恢复或彻底清除。</p>
          </div>
          <div v-else class="trash-grid">
            <div v-for="item in trashItems" :key="item.type + item.hash" class="trash-card">
              <div class="trash-card-header">
                <span class="trash-type-badge" :class="item.type === 'video' ? 'type-video' : 'type-gallery'">
                  {{ item.type === 'video' ? '视频' : '图集' }}
                </span>
                <span class="trash-time">{{ formatTrashTime(item.trashed_at) }}</span>
              </div>
              <div class="trash-card-body">
                <h4 class="trash-title">{{ item.title || '(无标题)' }}</h4>
                <div class="trash-meta">
                  <span class="meta-line">{{ item.owner || '—' }}</span>
                  <span class="meta-line">{{ formatSize(item.size) }}</span>
                </div>
                <div class="trash-actions">
                  <button class="btn btn-primary btn-sm" @click="restoreTrashItem(item)">恢复</button>
                  <button class="btn btn-danger btn-sm" @click="purgeTrashItem(item)">永久删除</button>
                </div>
              </div>
            </div>
          </div>
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
              <div class="info-row">
                <span class="label">开源仓库</span>
                <a class="value repo-link" :href="repoUrl" target="_blank" rel="noopener noreferrer">{{ repoUrl }}</a>
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
                  <span class="hot-rank">{{ Number(i) + 1 }}</span>
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
                  <span class="hot-rank fav">{{ Number(i) + 1 }}</span>
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
                  <small style="color:var(--text-tertiary); font-size:11px; display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:300px;" :title="video.local_path">{{ video.local_path }}</small>
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
        <Pagination
          v-if="videoTotal > VIDEO_PAGE_SIZE"
          :current-page="videoPage"
          :total-pages="videoTotalPages"
          :total="videoTotal"
          :page-range="videoPageRange"
          @change="(p: number) => { videoPage = p; fetchVideos(false) }"
        />
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
            <div class="search-box-inline">
              <svg class="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>
              </svg>
              <input
                v-model="resourceSearch"
                @keyup.enter="fetchResources()"
                type="text"
                placeholder="搜索标题..."
                class="search-input"
              />
            </div>
            <button class="action-btn" @click="fetchResources()">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
              搜索
            </button>
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
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M10 9l5 3-5 3V9z"/></svg>
            视频
          </button>
          <button
            class="subtab-btn"
            :class="{ active: resourceTypeFilter === 'gallery' }"
            @click="resourceTypeFilter = 'gallery'; fetchResources()"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
            图集
          </button>
          <button
            class="subtab-btn"
            :class="{ active: resourceTypeFilter === 'post' }"
            @click="resourceTypeFilter = 'post'; fetchResources()"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>
            帖子
          </button>
          <button
            class="subtab-btn"
            :class="{ active: resourceTypeFilter === 'text' }"
            @click="resourceTypeFilter = 'text'; fetchResources()"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8"/><path d="M16 17H8"/></svg>
            文本
          </button>
        </div>

        <!-- 显示隐藏资源开关（公共层属性 resource_index.hidden） -->
        <label class="show-hidden-toggle">
          <input type="checkbox" v-model="showHiddenResources" @change="fetchResources()" />
          <span>显示已隐藏的资源</span>
        </label>

        <div v-if="resourceLoading" class="loading-state"><div class="loading-spinner"></div><p>加载中...</p></div>
        <div v-else class="resource-table-wrap">
          <div class="res-grid">
            <div
              v-for="r in resources"
              :key="r.type + ':' + r.id"
              class="res-card"
              :class="{ 'is-hidden': r.hidden }"
            >
              <div class="res-card-cover">
                <img
                  v-if="r.cover && !isCoverBroken(r)"
                  :src="withThumbToken(r.cover)"
                  class="res-card-img"
                  @error="onCoverError(r)"
                />
                <div v-else class="res-card-img res-card-placeholder">{{ typeIcon(r.type) }}</div>
                <span class="res-card-type" :class="'type-' + r.type">{{ typeLabel(r.type) }}</span>
                <span v-if="r.hidden" class="res-card-hidden">已隐藏</span>
              </div>
              <div class="res-card-body">
                <div class="res-card-title" :title="r.title">{{ r.title }}</div>
                <div class="res-card-meta">
                  <template v-if="r.type === 'video'">
                    <span>{{ formatSize(r.file_size) }}</span>
                    <span>{{ formatDuration(r.duration) }}</span>
                    <span>{{ formatResolution(r.width, r.height) }}</span>
                  </template>
                  <span v-else-if="r.type === 'gallery'">{{ formatCount(r.page_count) }} 张</span>
                  <span v-else-if="r.type === 'post'">{{ formatCount(r.content_length) }} 字</span>
                  <span v-else-if="r.type === 'text'">{{ formatCount(r.char_count) }} 字</span>
                </div>
                <div class="res-card-foot">
                  <span class="res-card-lib">{{ libraryName(r.library_id) }}</span>
                  <span>{{ formatDate(r.updated_at) }}</span>
                </div>
                <div class="res-card-actions">
                  <button
                    class="res-act"
                    :class="{ active: r.hidden }"
                    @click="toggleResourceHidden(r)"
                    :title="r.hidden ? '已隐藏，点击显示' : '点击隐藏'"
                    :disabled="togglingHidden === r.resource_index_id"
                  >
                    <svg v-if="r.hidden" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                    <svg v-else width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>
                    <span class="btn-label">{{ r.hidden ? '显示' : '隐藏' }}</span>
                  </button>
                  <button class="res-act" @click="editResource(r)" title="编辑">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                    <span class="btn-label">编辑</span>
                  </button>
                  <button class="res-act danger" @click="deleteResource(r)" title="删除">
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    <span class="btn-label">删除</span>
                  </button>
                </div>
              </div>
            </div>
            <div v-if="resources.length === 0" class="res-empty">暂无资源</div>
          </div>
        </div>

        <Pagination
          v-if="resourceTotal > RESOURCE_PAGE_SIZE"
          :current-page="resourcePage"
          :total-pages="resourceTotalPages"
          :total="resourceTotal"
          :page-range="resourcePageRange"
          @change="(p: number) => { resourcePage = p; fetchResources(false) }"
        />
      </div>

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

            <!-- 自动生成实时进度 -->
            <div v-if="thumbProgress && (thumbProgress.running || thumbProgress.processed > 0)" class="auto-progress-box">
              <div class="auto-progress-header">
                <span class="auto-progress-title">
                  {{ thumbProgress.running ? '生成进度（进行中）' : '生成进度（已完成）' }}
                </span>
                <span class="auto-progress-count">
                  {{ thumbProgress.processed }} / {{ thumbProgress.total }}
                </span>
              </div>
              <div class="auto-progress-bar">
                <div
                  class="auto-progress-fill"
                  :style="{ width: thumbProgressPercent + '%' }"
                ></div>
              </div>
              <div class="auto-progress-meta">
                <span class="text-ok">成功 {{ thumbProgress.success }}</span>
                <span class="text-error">失败 {{ thumbProgress.failed }}</span>
                <span v-if="thumbProgress.pending !== undefined" class="text-muted">待处理 {{ thumbProgress.pending }}</span>
                <span v-if="thumbProgress.running && thumbProgress.current" class="auto-progress-current">
                  当前: {{ thumbProgress.current }}
                </span>
              </div>
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
          <p>未发现 dbox- 前缀的 NSSM 服务</p>
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
                  @click="openServiceControlConfirm(svc, 'stop')"
                  :disabled="isOperating(svc.service_name)"
                >
                  ⏹ 停止
                </button>
                <button
                  class="action-btn"
                  @click="openServiceControlConfirm(svc, 'restart')"
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
            <div class="scan-actions">
              <button class="action-btn primary" @click="scanAllLibraries('incremental')" :disabled="scanAllScanning" v-if="userStore.isAdmin" title="仅同步自上次扫描以来变化的文件，最快，日常首选">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
                {{ scanAllScanning && scanAllMode === 'incremental' ? '增量同步中...' : '🔄 增量同步' }}
              </button>
              <button class="action-btn" @click="scanAllLibraries('verify')" :disabled="scanAllScanning" v-if="userStore.isAdmin" title="仅清理磁盘已不存在的失效记录，不枚举新增文件">
                {{ scanAllScanning && scanAllMode === 'verify' ? '校验清理中...' : '🧹 校验清理' }}
              </button>
              <button class="action-btn warn" @click="scanAllLibraries('full')" :disabled="scanAllScanning" v-if="userStore.isAdmin" title="全量枚举磁盘并比对（慢，仅数据严重不一致的小库使用）">
                {{ scanAllScanning && scanAllMode === 'full' ? '全量重建中...' : '⚠ 全量重建' }}
              </button>
            </div>
            <button class="action-btn primary" @click="editingLibrary = null; showLibraryModal = true" v-if="userStore.isAdmin">+ 新建资源库</button>
            <div class="scan-config-panel" v-if="scanConfigLoaded">
              <div class="scan-config-title">扫描策略</div>
              <label class="scan-switch">
                <input type="checkbox" v-model="scanConfig.library_watch_enabled" :disabled="scanSaving" @change="scanSaved = false" />
                <span class="scan-switch-text">
                  <span class="scan-switch-label">文件夹实时监控</span>
                  <span class="scan-switch-desc">开启后，磁盘文件新增 / 删除 / 改名会即时同步进资源库（后台持续监听，无需手动操作）</span>
                </span>
              </label>
              <label class="scan-switch">
                <input type="checkbox" v-model="scanConfig.auto_scan_on_startup" :disabled="scanSaving" @change="scanSaved = false" />
                <span class="scan-switch-text">
                  <span class="scan-switch-label">启动时自动扫描</span>
                  <span class="scan-switch-desc">每次服务启动时，对全部资源库做一次全量扫描（仅在启动时执行一次，与上面的实时监控互不影响）</span>
                </span>
              </label>
              <button class="action-btn primary scan-config-save" @click="saveScanConfig" :disabled="scanSaving">
                {{ scanSaving ? '保存中...' : (scanSaved ? '已保存 ✓' : '保存设置') }}
              </button>
            </div>
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
                <span class="stat-pill">📄 视频 {{ lib.video_count || 0 }}</span>
                <span class="stat-pill">🖼️ 图集 {{ lib.gallery_count || 0 }}</span>
                <span class="stat-pill">📝 帖子 {{ lib.post_count || 0 }}</span>
                <span class="stat-pill">📄 文本 {{ lib.text_count || 0 }}</span>
              </div>
              <button class="view-resources-btn" @click="openResourceViewer(lib)">
                查看资源（{{ Number(lib.video_count || 0) + Number(lib.gallery_count || 0) + Number(lib.post_count || 0) + Number(lib.text_count || 0) }}）
              </button>
              <p class="library-path">{{ lib.db_path }}/{{ lib.db_file }}</p>
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

    <!-- 资源库资源查看弹窗 -->
    <div v-if="resourceViewer.open" class="modal-overlay" @click="closeResourceViewer()">
      <div class="modal-content modal-large" @click.stop>
        <div class="modal-header">
          <h3>{{ resourceViewer.libName }} · 资源列表</h3>
          <button class="close-btn" @click="closeResourceViewer()">×</button>
        </div>
        <div class="modal-body">
          <div class="resource-viewer-tabs">
            <button
              v-for="t in resourceViewer.types"
              :key="t.key"
              :class="['rv-tab', { active: resourceViewer.activeType === t.key }]"
              @click="resourceViewer.activeType = t.key; loadLibraryResources()"
            >
              {{ t.label }} ({{ t.count }})
            </button>
          </div>
          <div v-if="resourceViewer.loading" class="empty-tip">加载中…</div>
          <div v-else-if="resourceViewer.items.length === 0" class="empty-tip">该分类下暂无资源</div>
          <ul v-else class="resource-viewer-list">
            <li v-for="item in resourceViewer.items" :key="item.type + '-' + item.id" class="rv-item">
              <span class="rv-type" :class="'rv-type-' + item.type">{{ typeLabel(item.type) }}</span>
              <span class="rv-title" :title="item.title">{{ item.title || '未命名' }}</span>
              <button class="action-btn small" @click="editResourceFromViewer(item)">编辑</button>
            </li>
          </ul>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="closeResourceViewer()">关闭</button>
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

    <!-- 停止/重启服务二次确认对话框 -->
    <div v-if="showServiceConfirm" class="dialog-overlay" @click.self="showServiceConfirm = false">
      <div class="dialog">
        <h3>确认操作</h3>
        <p>
          确定要对服务「<strong>{{ serviceConfirmName }}</strong>」执行
          <strong>{{ serviceConfirmAction === 'stop' ? '停止' : '重启' }}</strong>
          操作吗？
        </p>
        <p class="dialog-tip">{{ serviceConfirmAction === 'stop' ? '停止后该服务将不再运行，可能影响相关功能。' : '重启会先停止再启动该服务，期间服务会短暂不可用。' }}</p>
        <div class="dialog-buttons">
          <button class="btn-secondary" @click="showServiceConfirm = false">取消</button>
          <button class="btn-danger" @click="confirmServiceControl">{{ serviceConfirmAction === 'stop' ? '停止' : '重启' }}</button>
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
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 24px;
  min-width: 360px;
  max-width: 480px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
}

.dialog h3 {
  margin: 0 0 16px 0;
  font-size: 18px;
  color: var(--text-primary);
}

.dialog p {
  margin: 0 0 16px 0;
  color: var(--text-tertiary);
  line-height: 1.5;
}

.dialog-checkbox {
  margin-bottom: 20px;
  padding: 12px;
  background: var(--bg-surface-hover);
  border-radius: 8px;
}

.dialog-checkbox label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  color: var(--text-secondary);
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

.dialog-tip {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.btn-secondary {
  padding: 8px 16px;
  background: var(--bg-surface-hover);
  border: none;
  border-radius: 6px;
  color: var(--text-secondary);
  cursor: pointer;
  font-size: 14px;
}

.btn-secondary:hover {
  background: var(--bg-surface);
}

.btn-danger {
  padding: 8px 16px;
  background: var(--danger);
  border: none;
  border-radius: 6px;
  color: white;
  cursor: pointer;
  font-size: 14px;
}

.btn-danger:hover {
  opacity: 0.85;
}

.admin-page {
  min-height: 100vh;
  background: var(--bg-base);
  padding: 24px;
  color: var(--text-primary);
}

.admin-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding: 16px 24px;
  background: var(--bg-surface);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.admin-header h1 {
  margin: 0;
  font-size: 24px;
  color: var(--text-primary);
}

.header-health {
  flex: 1;
  display: flex;
  justify-content: center;
}

.overall-health {
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 600;
}

.alert-badge {
  margin-left: 8px;
  padding: 0 7px;
  min-width: 18px;
  height: 18px;
  line-height: 18px;
  text-align: center;
  border-radius: 9px;
  background: #ef4444;
  color: #fff;
  font-size: 11px;
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
  background: var(--accent);
  color: white;
}

.role-badge.root {
  background: var(--danger);
}

.username {
  font-size: 14px;
  color: var(--text-tertiary);
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
  background: var(--bg-surface);
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

/* 卡片顶部标题栏：圆角顶部 + 浅色底 + 细分隔线，与下方卡片内容视觉统一 */
.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: var(--accent-soft);
  color: var(--accent);
  border-bottom: 1px solid var(--border-color, var(--border-default));
}

.card-header:first-child {
  border-top-left-radius: inherit;
  border-top-right-radius: inherit;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-secondary);
}

.version-badge {
  padding: 4px 10px;
  background: var(--accent-soft);
  color: var(--accent);
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
  border-bottom: 1px solid var(--border-default);
}

.info-row:last-child {
  border-bottom: none;
}

.label {
  font-size: 13px;
  color: var(--text-tertiary);
}

.value {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.value.highlight {
  color: var(--accent);
  font-size: 16px;
  font-weight: 700;
}

.value.path {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: var(--text-tertiary);
}

.update-badge {
  padding: 2px 8px;
  background: var(--success);
  color: white;
  border-radius: 4px;
  font-size: 11px;
}

.repo-link {
  color: var(--accent);
  text-decoration: none;
  word-break: break-all;
}
.repo-link:hover {
  text-decoration: underline;
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
  background: var(--bg-surface);
  border-radius: 8px;
}

.stat-icon {
  width: 48px;
  height: 48px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-surface);
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
  color: var(--text-primary);
}

.stat-label {
  font-size: 12px;
  color: var(--text-secondary);
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
  color: var(--text-tertiary);
  margin-bottom: 8px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border-default);
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
  background: var(--bg-surface-hover);
}

.hot-rank {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  border-radius: 50%;
  background: var(--danger);
  color: var(--text-on-accent);
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

.hot-rank.fav {
  background: var(--warning);
}

.hot-name {
  flex: 1;
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hot-count {
  font-size: 13px;
  font-weight: 600;
  color: var(--danger);
}

.hot-empty {
  font-size: 12px;
  color: var(--text-tertiary);
  padding: 6px 4px;
}

.libdist-card .card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
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
  background: var(--bg-surface);
  border-radius: 8px;
}

.path-key {
  font-size: 11px;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.path-value {
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: var(--text-secondary);
  word-break: break-all;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: var(--bg-surface);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
  margin-bottom: 20px;
}

.section-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-secondary);
}

.header-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}

.scan-all-status {
  padding: 8px 20px;
  font-size: 13px;
  color: var(--success);
  background: var(--success-soft);
  border-bottom: 1px solid var(--border-default);
}

.scan-actions {
  display: inline-flex;
  gap: 8px;
}

.action-btn.warn {
  background: var(--warning-soft, #fff7ed);
  color: var(--warning, #d97706);
  border: 1px solid var(--warning-border, #fdba74);
}

.action-btn.warn:hover {
  background: var(--warning, #d97706);
  color: #fff;
}

.scan-config-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-left: auto;
  padding: 12px 16px;
  border: 1px solid var(--border-default);
  border-radius: 10px;
  background: var(--bg-surface, #fff);
  max-width: 420px;
}

.scan-config-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.scan-switch {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  user-select: none;
}

.scan-switch input {
  width: 16px;
  height: 16px;
  margin-top: 2px;
  cursor: pointer;
  accent-color: var(--accent, #3b82f6);
  flex-shrink: 0;
}

.scan-switch-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.scan-switch-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}

.scan-switch-desc {
  font-size: 12px;
  line-height: 1.4;
  color: var(--text-tertiary, #8a8f98);
}

.scan-config-save {
  align-self: flex-end;
  margin-top: 2px;
}

.scan-saving {
  font-size: 12px;
  color: var(--text-secondary);
}

.log-container {
  max-height: 300px;
  overflow-y: auto;
  padding: 12px;
  background: var(--bg-surface);
}

.log-item {
  padding: 6px 12px;
  font-family: 'Courier New', monospace;
  font-size: 12px;
  color: var(--text-secondary);
  border-left: 3px solid transparent;
}

.log-item.error {
  color: var(--danger);
  border-left-color: var(--danger);
  background: var(--danger-soft);
}

.log-item.success {
  color: var(--success);
  border-left-color: var(--success);
}

/* 标签页导航 */
.admin-tabs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 4px;
  padding: 0 24px 16px;
  background: var(--bg-surface);
  border-bottom: 1px solid var(--border-default);
  margin: 0 -24px 24px;
}

.tab-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  border: 1px solid var(--border-default);
  border-radius: 10px;
  background: var(--bg-surface-hover);
}

.tab-group-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-tertiary);
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
  color: var(--text-tertiary);
  cursor: pointer;
  transition: all 0.3s ease;
}

.tab-btn:hover {
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
}

.tab-btn.active {
  background: var(--accent);
  color: var(--text-on-accent);
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
  border: 1px solid var(--border-default);
  border-radius: 8px;
  font-size: 14px;
  width: 240px;
  background: var(--bg-surface);
  color: var(--text-primary);
}

.search-box-inline {
  display: flex;
  align-items: center;
  gap: 6px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 0 10px;
}

.search-box-inline .search-icon {
  color: var(--text-tertiary);
  flex-shrink: 0;
}

.search-box-inline .search-input {
  border: none;
  background: transparent;
  width: 180px;
  padding: 8px 0;
}

.search-select {
  padding: 8px 36px 8px 16px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  font-size: 14px;
  background-color: var(--bg-surface);
  color: var(--text-primary);
  cursor: pointer;
  -webkit-appearance: none;
  appearance: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%23a0a0b0' stroke-width='2'><path d='M6 9l6 6 6-6'/></svg>");
  background-repeat: no-repeat;
  background-position: right 12px center;
  transition: border-color 0.3s ease, background-color 0.3s ease;
}

.search-select:hover {
  background-color: var(--bg-surface-2);
}

.search-select:focus {
  outline: none;
  border-color: var(--accent);
}

.data-table-container {
  background: var(--bg-surface);
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

/* 资源表格容器 */
.resource-table-wrap {
  width: 100%;
}

/* 资源管理：响应式卡片网格（封面优先的现代媒体库布局，桌面/移动统一） */
.res-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: 16px;
  width: 100%;
}

.res-card {
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 14px;
  overflow: hidden;
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}
.res-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 28px rgba(0, 0, 0, 0.12);
  border-color: var(--border-default);
}
.res-card.is-hidden { opacity: 0.58; }

/* 封面区 */
.res-card-cover {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--bg-surface-hover);
  overflow: hidden;
}
.res-card-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.res-card-cover .res-card-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 40px;
  line-height: 1;
}
.res-card-type {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 3px 9px;
  border-radius: 7px;
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: rgba(15, 18, 25, 0.55);
  backdrop-filter: blur(4px);
}
.res-card-type.type-video { box-shadow: inset 0 0 0 1px rgba(96, 165, 250, 0.6); }
.res-card-type.type-gallery { box-shadow: inset 0 0 0 1px rgba(192, 132, 252, 0.6); }
.res-card-type.type-post { box-shadow: inset 0 0 0 1px rgba(251, 191, 36, 0.6); }
.res-card-type.type-text { box-shadow: inset 0 0 0 1px rgba(52, 211, 153, 0.6); }
.res-card-hidden {
  position: absolute;
  top: 8px;
  right: 8px;
  padding: 3px 9px;
  border-radius: 7px;
  font-size: 11px;
  font-weight: 600;
  color: var(--warning);
  background: var(--warning-soft);
}

/* 信息区 */
.res-card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px 14px;
  flex: 1;
}
.res-card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.res-card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
  color: var(--text-tertiary);
}
.res-card-meta span {
  background: var(--bg-surface-hover);
  border-radius: 6px;
  padding: 2px 8px;
  white-space: nowrap;
}
.res-card-foot {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
  font-size: 11px;
  color: var(--text-tertiary);
}
.res-card-foot span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.res-card-foot .res-card-lib { color: var(--text-secondary); }

/* 空状态 */
.res-empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 64px 20px;
  color: var(--text-tertiary);
  background: var(--bg-surface);
  border: 1px dashed var(--border-subtle);
  border-radius: 14px;
  font-size: 14px;
}

/* 操作栏：卡片底部始终可见，均分分布、带分隔线，不再挤在角落 */
.res-card-actions {
  display: flex;
  gap: 4px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid var(--border-subtle);
}
.res-act {
  flex: 1 1 0;
  min-width: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  border-radius: 9px;
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  border: 1px solid var(--border-subtle);
  cursor: pointer;
  font-size: 13px;
  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
}
.res-act .btn-label { display: inline; line-height: 1; }
.res-act:hover { color: var(--accent); border-color: var(--accent); }
.res-act.active { color: var(--accent); border-color: var(--accent); background: var(--accent-soft); }
.res-act.danger { color: var(--danger); }
.res-act.danger:hover { background: var(--danger-soft); border-color: var(--danger); color: var(--danger); }
.res-act:disabled { opacity: 0.5; cursor: not-allowed; }

/* 较宽屏：卡片略小、列更多 */
@media (min-width: 1600px) {
  .res-grid { grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); }
}

/* 资源管理容器（卡片网格外包） */
.resource-table-wrap { width: 100%; }

.show-hidden-toggle { display: inline-flex; align-items: center; gap: 8px; margin: 12px 0 8px; padding: 8px 12px; background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 8px; color: var(--text-secondary); font-size: 13px; cursor: pointer; user-select: none; transition: all 0.2s; }
.show-hidden-toggle:hover { border-color: var(--accent); color: var(--accent); }
.show-hidden-toggle input { width: 16px; height: 16px; accent-color: var(--accent); }
.muted { color: var(--text-tertiary); font-weight: 400; font-size: 13px; }

.data-table th,
.data-table td {
  padding: 14px 16px;
  text-align: left;
  border-bottom: 1px solid var(--border-default);
}

.data-table th {
  background: var(--bg-surface);
  font-weight: 600;
  font-size: 13px;
  color: var(--text-tertiary);
  position: sticky;
  top: 0;
  z-index: 10;
  cursor: pointer;
  user-select: none;
  transition: background 0.2s;
}

.data-table th:hover {
  background: var(--bg-surface-hover);
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
  color: var(--accent);
}

.data-table th.sort-desc::after {
  content: '↓';
  opacity: 1;
  color: var(--accent);
}

.data-table td {
  color: var(--text-secondary);
}

.data-table tbody tr {
  transition: background 0.15s ease;
}

.data-table tbody tr:hover {
  background: var(--accent-soft);
}

.data-table tbody tr.selected {
  background: var(--info-soft);
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
  color: var(--text-tertiary);
  gap: 12px;
}

.loading-state.mobile {
  padding: 40px 20px;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--border-default);
  border-top-color: var(--accent);
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
  color: var(--text-tertiary);
  background: var(--bg-surface);
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}

.empty-state.mobile {
  padding: 40px 20px;
}

/* 回收站空状态 */
.trash-empty {
  padding: 80px 20px;
}
.trash-empty svg {
  color: var(--text-quaternary, #cbd2dc);
  margin-bottom: 16px;
}
.trash-empty p {
  font-size: 16px;
  margin: 0;
}
.trash-empty .empty-sub {
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-quaternary, #aab2c0);
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 12px;
  opacity: 0.6;
}

.empty-text {
  font-size: 16px;
  color: var(--text-tertiary);
  font-weight: 500;
}

.empty-hint {
  font-size: 13px;
  color: var(--text-tertiary);
  margin-top: 8px;
}

/* 分页组件 */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 16px;
  margin-top: 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.page-btn {
  min-width: 36px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
}

.page-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover);
  color: var(--accent);
}

.page-btn:disabled {
  color: var(--text-tertiary);
  cursor: not-allowed;
  opacity: 0.5;
}

.page-btn.active {
  background: var(--accent);
  color: var(--text-on-accent);
  font-weight: 600;
}

.page-ellipsis {
  color: var(--text-tertiary);
  padding: 0 8px;
}

.page-info {
  font-size: 13px;
  color: var(--text-tertiary);
  margin-left: 8px;
}

/* 资源管理：类型过滤标签组 */
.subtab-group {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 16px;
  padding: 6px;
  background: var(--bg-surface-hover);
  border-radius: 12px;
  width: fit-content;
}

.subtab-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 6px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.2;
  cursor: pointer;
  transition: all 0.2s ease;
  white-space: nowrap;
}

.subtab-btn:hover {
  background: var(--bg-surface);
  color: var(--text-primary);
}

.subtab-btn.active {
  background: var(--bg-surface);
  color: var(--accent);
  border-color: var(--accent);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.page-info {
  font-size: 13px;
  color: var(--text-tertiary);
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
  background: var(--bg-surface-hover);
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s ease;
  /* 同 .btn：须显式颜色，避免深色背景下黑底黑字 */
  color: var(--text-primary);
}

.action-btn svg {
  flex-shrink: 0;
}

.action-btn:hover {
  background: var(--bg-surface);
}

.action-btn.primary {
  background: var(--accent);
  color: var(--text-on-accent);
}

.action-btn.primary:hover {
  opacity: 0.9;
}

.action-btn.danger {
  background: var(--danger);
  color: var(--text-on-accent);
}

.action-btn.danger:hover {
  opacity: 0.85;
}

.action-btn.success {
  background: var(--success);
  color: var(--text-on-accent);
}

.action-btn.success:hover {
  opacity: 0.85;
}

/* 扫描进度反馈 */
.scan-progress {
  font-size: 14px;
  color: var(--text-secondary);
  font-weight: 500;
}

.scan-progress-sub {
  font-size: 12px;
  color: var(--text-secondary);
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
  background: var(--success-soft);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

.scan-summary-text {
  font-size: 14px;
  color: var(--text-secondary);
}

.scan-summary-text b {
  color: var(--success);
}

.scan-summary-text .new-count {
  color: var(--warning);
}

/* 扫描文件夹失败提示 */
.scan-error-banner {
  margin: 12px 0;
  padding: 12px 16px;
  background: var(--warning-soft);
  border: 1px solid var(--border-default);
  border-radius: 8px;
}

.scan-error-title {
  font-size: 13px;
  color: var(--warning);
  font-weight: 500;
  margin-bottom: 6px;
}

.scan-error-list {
  margin: 0;
  padding-left: 20px;
  font-size: 13px;
  color: var(--text-secondary);
}

.scan-error-list li {
  margin: 2px 0;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.2s ease;
}

/* 资源列表操作按钮间距 */
.res-table .icon-btn {
  margin-left: 4px;
}
.res-table .icon-btn:first-child {
  margin-left: 0;
}

.icon-btn:hover {
  background: var(--bg-surface-hover);
  color: var(--accent);
  border-color: var(--accent);
  transform: translateY(-1px);
}

.icon-btn.danger:hover {
  background: var(--danger-soft);
  color: var(--danger);
  border-color: var(--danger);
}

.icon-btn.active {
  background: var(--accent-soft);
  color: var(--accent);
  border-color: var(--accent);
}

/* 角色标签 */
.role-tag {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.role-tag.root {
  background: var(--danger-soft);
  color: var(--danger);
}

.role-tag.admin {
  background: var(--info-soft);
  color: var(--info);
}

.role-tag.user {
  background: var(--success-soft);
  color: var(--success);
}

/* 配置表单 */
.config-form {
  background: var(--bg-surface);
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
  color: var(--text-secondary);
  font-weight: 500;
}

.form-group input,
.form-group select,
.form-group textarea {
  width: 100%;
  padding: 10px 14px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  font-size: 14px;
  transition: border-color 0.3s ease;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
  outline: none;
  border-color: var(--accent);
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
  background-color: var(--text-secondary);
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
  background: var(--accent);
}

input:checked + .slider:before {
  transform: translateX(24px);
}

.form-actions {
  margin-top: 24px;
  padding-top: 20px;
  border-top: 1px solid var(--border-default);
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
  align-items: flex-start;
  justify-content: center;
  z-index: 1000;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 24px 16px;
}

.modal-content {
  background: var(--bg-surface);
  border-radius: 12px;
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow: hidden;
  margin: auto 0;
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
  border-bottom: 1px solid var(--border-default);
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
  color: var(--text-tertiary);
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
  border-top: 1px solid var(--border-default);
}

/* Toast */
.toast {
  position: fixed;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.8);
  color: var(--text-on-accent);
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

.form-hint {
  display: block;
  margin-top: 6px;
  color: var(--text-secondary);
  font-size: 12px;
}

.modal-info {
  margin: 0 0 16px 0;
  padding: 12px;
  background: var(--info-soft);
  border-radius: 8px;
  color: var(--accent);
  font-size: 14px;
}

/* 响应式适配 */
@media (max-width: 768px) {
  .admin-page {
    padding: 12px;
  }
  
  .admin-tabs {
    flex-wrap: wrap;
    padding: 0 12px 12px;
    margin: 0 -12px 16px;
    overflow-x: visible;
    row-gap: 10px;
  }

  .tab-group {
    flex: 1 1 auto;
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
    background: var(--bg-surface);
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
    background: var(--bg-surface-hover);
  }

.video-card-mobile .card-thumb-placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 24px;
  color: var(--text-secondary);
  background: var(--bg-surface-2);
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
    color: var(--text-secondary);
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    -webkit-box-orient: vertical;
    line-height: 1.4;
  }

  .video-card-mobile .card-meta {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    font-size: 11px;
    color: var(--text-secondary);
  }

  .video-card-mobile .card-meta span {
    display: flex;
    align-items: center;
    gap: 3px;
  }

  .video-card-mobile .card-path {
    font-size: 11px;
    color: var(--text-tertiary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

.video-card-mobile .card-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding-top: 8px;
  border-top: 1px solid var(--border-default);
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
    background: var(--bg-surface);
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
    color: var(--text-secondary);
  }

  .mobile-selection-bar .select-all input {
    width: 18px;
    height: 18px;
    cursor: pointer;
  }

  .mobile-selection-bar .selected-count {
    flex: 1;
    font-size: 12px;
    color: var(--text-tertiary);
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
  border: 1px solid var(--border-color, var(--border-default));
  border-radius: 8px;
  background: var(--card-bg, var(--border-default));
  cursor: pointer;
  font-size: 13px;
  color: var(--text-tertiary);
  transition: all 0.2s;
  white-space: nowrap;
}

.folder-tab:hover {
  border-color: var(--primary, var(--accent));
  color: var(--primary, var(--accent));
  background: rgba(24, 144, 255, 0.04);
}

.folder-tab.active {
  background: var(--primary, var(--accent));
  color: var(--text-on-accent);
  border-color: var(--primary, var(--accent));
}

.folder-tab.active .tab-count {
  background: rgba(255, 255, 255, 0.3);
  color: var(--text-on-accent);
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
  color: var(--text-secondary);
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

  background: var(--bg-surface);

  border-radius: 12px;

  padding: 24px;

  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);

}



.import-config h4,

.scan-results h4,

.import-progress h4 {

  margin: 0 0 20px 0;

  font-size: 18px;

  color: var(--text-primary);

}



.input-group {

  display: flex;

  gap: 12px;

}



.folder-input {

  flex: 1;

  padding: 12px 16px;

  font-size: 14px;

  border: 2px solid var(--border-default);

  border-radius: 8px;

  transition: border-color 0.3s;

}



.folder-input:focus {

  outline: none;

  border-color: var(--accent);

}



.form-hint {

  display: block;

  margin-top: 8px;

  color: var(--text-tertiary);

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

  background: var(--bg-surface);

  border-radius: 8px;

  margin-bottom: 16px;

}



.results-toolbar .select-all {

  font-weight: 600;

  color: var(--text-primary);

}



.results-actions {

  display: flex;

  align-items: center;

  gap: 16px;

}



.selected-count {

  font-size: 14px;

  color: var(--accent);

  font-weight: 600;

}



.video-list {

  max-height: 500px;

  overflow-y: auto;

  border: 1px solid var(--border-default);

  border-radius: 8px;

}



.video-item {

  display: flex;

  align-items: center;

  gap: 12px;

  padding: 16px;

  border-bottom: 1px solid var(--border-default);

  cursor: pointer;

  transition: background-color 0.2s;

}



.video-item:last-child {

  border-bottom: none;

}



.video-item:hover:not(.existing) {

  background-color: var(--bg-surface-hover);

}



.video-item.selected {

  background-color: var(--accent-soft);

  border-left: 4px solid var(--accent);

}



.video-item.existing {

  background-color: var(--bg-surface-2);

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

  background-color: var(--text-tertiary);

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

  color: var(--text-primary);

  margin-bottom: 4px;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}



.video-meta {

  display: flex;

  gap: 16px;

  font-size: 12px;

  color: var(--text-tertiary);

}



.video-meta span {

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}



.import-actions {

  margin-top: 24px;

  padding-top: 24px;

  border-top: 1px solid var(--border-default);

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

  background-color: var(--success-soft);

}



.stat-item.warning {

  background-color: var(--warning-soft);

}



.stat-item.error {

  background-color: var(--danger-soft);

}



.stat-label {

  display: block;

  font-size: 14px;

  color: var(--text-tertiary);

  margin-bottom: 8px;

}



.stat-value {

  display: block;

  font-size: 32px;

  font-weight: 700;

}



.stat-item.success .stat-value {

  color: var(--success);

}



.stat-item.warning .stat-value {

  color: var(--warning);

}



.stat-item.error .stat-value {

  color: var(--danger);

}



.import-errors {

  margin-top: 20px;

  padding: 16px;

  background-color: var(--danger-soft);

  border-radius: 8px;

}



.import-errors h5 {

  margin: 0 0 12px 0;

  font-size: 14px;

  color: var(--danger);

}



.import-errors ul {

  margin: 0;

  padding-left: 20px;

  font-size: 13px;

  color: var(--text-tertiary);

}



.import-errors li {

  margin-bottom: 8px;

}



.card {

  background: var(--bg-surface);

  border-radius: 12px;

  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);

  overflow: hidden;

}



.required {

  color: var(--danger);

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

  background: var(--bg-surface-hover);

  border-radius: 8px;

  margin-bottom: 16px;

  font-size: 14px;

}



.path-label {

  color: var(--text-tertiary);

  margin-right: 8px;

}



.path-value {

  color: var(--text-primary);

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

  border: 1px solid var(--border-default);

  background: var(--bg-surface);

  border-radius: 6px;

  cursor: pointer;

  font-size: 14px;

  transition: all 0.2s;

}



.nav-btn:hover:not(:disabled) {

  background: var(--bg-surface-hover);

  border-color: var(--accent);

}



.nav-btn:disabled {

  opacity: 0.5;

  cursor: not-allowed;

}



.folder-list-container {

  flex: 1;

  overflow-y: auto;

  border: 1px solid var(--border-default);

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

  border: 1px solid var(--border-default);

  border-radius: 6px;

  background: var(--bg-surface);

  color: var(--text-primary);

  font-size: 14px;

}

.new-folder-input:focus {

  outline: none;

  border-color: var(--accent);

}



.loading-state {

  display: flex;

  flex-direction: column;

  align-items: center;

  justify-content: center;

  padding: 60px;

  color: var(--text-tertiary);

}



.loading-spinner {

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

  background-color: var(--bg-surface-hover);

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

  color: var(--text-primary);

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}



.folder-type {

  font-size: 12px;

  color: var(--text-tertiary);

  margin-top: 2px;

}



.folder-arrow {

  color: var(--text-tertiary);

  font-size: 12px;

}



.library-card {

  background: var(--bg-surface);

  border: 1px solid var(--border-subtle);

  border-radius: 16px;

  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.08);

  overflow: hidden;

  transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;

}



.library-card:hover {

  transform: translateY(-3px);

  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.14);

  border-color: var(--border-default);

}



.library-card-header {

  display: flex;

  justify-content: space-between;

  align-items: center;

  gap: 12px;

  padding: 16px 20px;

  background: var(--accent-soft);

  color: var(--accent);

  border-bottom: 1px solid var(--border-color, var(--border-default));

}



.library-card-header h4 {

  margin: 0;

  font-size: 16px;

  font-weight: 600;

  color: var(--accent);

  flex: 1;

  min-width: 0;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

}



/* 右上角激活/禁用按钮 */

.toggle-active-btn {

  display: inline-flex;

  align-items: center;

  gap: 4px;

  padding: 5px 12px;

  border-radius: 20px;

  font-size: 12px;

  font-weight: 600;

  cursor: pointer;

  transition: all 0.2s ease;

  border: 1px solid transparent;

  white-space: nowrap;

}



.toggle-active-btn.active {

  background: rgba(16, 185, 129, 0.15);

  color: #34d399;

  border-color: rgba(16, 185, 129, 0.35);

}



.toggle-active-btn.active:hover {

  background: rgba(16, 185, 129, 0.25);

  transform: scale(1.04);

}



.toggle-active-btn.inactive {

  background: rgba(148, 163, 184, 0.15);

  color: #94a3b8;

  border-color: rgba(148, 163, 184, 0.35);

}



.toggle-active-btn.inactive:hover {

  background: rgba(148, 163, 184, 0.25);

  transform: scale(1.04);

}



.status-badge {

  display: inline-flex;

  align-items: center;

  gap: 4px;

  padding: 4px 10px;

  border-radius: 12px;

  font-size: 12px;

  font-weight: 500;

}



.status-badge.active {

  background: rgba(16, 185, 129, 0.15);

  color: #34d399;

}



.status-badge.inactive {

  background: rgba(148, 163, 184, 0.15);

  color: #94a3b8;

}



.library-card-body {

  padding: 18px;

}



.library-desc {

  color: var(--text-secondary);

  font-size: 14px;

  line-height: 1.5;

  margin: 0 0 14px 0;

}



.library-stats {

  display: flex;

  flex-wrap: wrap;

  gap: 8px;

  margin-bottom: 14px;

}

.view-resources-btn {
  display: inline-block;
  margin: 0 0 10px;
  padding: 6px 12px;
  font-size: 13px;
  color: var(--accent-color, #4f7cff);
  background: var(--accent-soft, rgba(79, 124, 255, 0.1));
  border: 1px solid var(--accent-border, rgba(79, 124, 255, 0.3));
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.15s;
}
.view-resources-btn:hover {
  background: var(--accent-soft-hover, rgba(79, 124, 255, 0.18));
}

/* 资源查看弹窗 */
.resource-viewer-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.rv-tab {
  padding: 6px 14px;
  border: 1px solid var(--border-color, #e2e8f0);
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary, #4a5568);
}
.rv-tab.active {
  background: var(--accent-color, #4f7cff);
  color: #fff;
  border-color: var(--accent-color, #4f7cff);
}
.resource-viewer-list {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 60vh;
  overflow-y: auto;
}
.rv-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-color, #eef1f5);
}
.rv-item:hover {
  background: var(--bg-secondary, #f8fafc);
}
.rv-type {
  flex-shrink: 0;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
}
.rv-type-video { background: #4f7cff; }
.rv-type-gallery { background: #f59e0b; }
.rv-type-post { background: #10b981; }
.rv-type-text { background: #8b5cf6; }
.rv-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}



.library-stats .stat-pill {

  display: inline-flex;

  align-items: center;

  gap: 4px;

  padding: 4px 10px;

  border-radius: 20px;

  background: var(--bg-surface-hover);

  border: 1px solid var(--border-default);

  font-size: 12px;

  font-weight: 500;

  color: var(--text-secondary);

}



.library-path {

  display: flex;

  align-items: center;

  gap: 6px;

  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;

  font-size: 12px;

  color: var(--text-tertiary);

  word-break: break-all;

  margin: 0;

}



.library-path::before {

  content: "📁";

  flex-shrink: 0;

}



.library-card-actions {

  display: flex;

  flex-wrap: wrap;

  gap: 8px;

  padding: 14px 18px;

  background: var(--bg-surface-hover);

  border-top: 1px solid var(--border-subtle);

}



.library-card-actions .action-btn {

  flex: 1 1 calc(33.333% - 6px);

  min-width: 64px;

  justify-content: center;

  padding: 7px 10px;

  font-size: 12px;

  font-weight: 500;

  border-radius: 8px;

  background: var(--bg-surface);

  border: 1px solid var(--border-default);

  color: var(--text-secondary);

  transition: all 0.2s ease;

}



.library-card-actions .action-btn:hover {

  background: var(--bg-surface-hover);

  border-color: var(--accent);

  color: var(--accent);

  transform: translateY(-1px);

}



.library-card-actions .action-btn.primary {

  background: var(--accent);

  border-color: var(--accent);

  color: var(--text-on-accent);

}



.library-card-actions .action-btn.primary:hover {

  opacity: 0.9;

}



.library-card-actions .action-btn.danger {

  background: transparent;

  border-color: var(--danger);

  color: var(--danger);

}



.library-card-actions .action-btn.danger:hover {

  background: var(--danger);

  color: var(--text-on-accent);

}



/* 文件夹管理样式 */

.folder-form {

  margin-bottom: 24px;

  padding: 16px;

}



.folder-form h4 {

  margin: 0 0 16px 0;

  color: var(--text-secondary);

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

  background: var(--accent-soft);

}



.folder-list-section h4 {

  margin: 0 0 16px 0;

  color: var(--text-secondary);

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

  color: var(--text-secondary);

  margin-bottom: 4px;

  word-break: break-all;

}



.folder-type-icon {

  margin-right: 4px;

}



.default-badge {

  display: inline-block;

  background: var(--success);

  color: white;

  font-size: 11px;

  padding: 2px 6px;

  border-radius: 4px;

  margin-right: 8px;

}



.folder-path {

  color: var(--text-tertiary);

  font-size: 13px;

  word-break: break-all;

  margin-bottom: 4px;

}



.folder-meta {

  font-size: 12px;

  color: var(--text-tertiary);

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

  border-bottom: 1px solid var(--border-default);

}



.permission-form h4,

.permission-list h4 {

  margin: 0 0 16px 0;

  font-size: 16px;

  color: var(--text-secondary);

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

  color: var(--text-secondary);

}



.library-modal .form-group {

  margin-bottom: 20px;

}



.library-modal label {

  display: block;

  font-size: 15px;

  font-weight: 500;

  color: var(--text-secondary);

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

  border: 2px solid var(--border-default);

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

  color: var(--text-tertiary);

}



.form-tip {

  display: flex;

  align-items: center;

  gap: 8px;

  padding: 12px 16px;

  background: var(--bg-surface);

  border-radius: 8px;

  font-size: 14px;

  color: var(--text-tertiary);

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

  /* button 不继承父级 color（UA 直接设 buttontext），深色主题下须显式指定，
     否则深色按钮背景上变成黑底黑字 */
  color: var(--text-primary);

}



.btn-primary {

  background: linear-gradient(135deg, #f97316 0%, #ea580c 100%);

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

  background: var(--bg-surface-hover);

  color: var(--text-secondary);

}



.btn-secondary:hover {

  background: var(--bg-surface);

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

  border: 1px solid var(--border-default);

  border-radius: 6px;

  background: var(--bg-surface);

  cursor: pointer;

  font-size: 13px;

  transition: all 0.2s;

  color: var(--text-primary);

}



.log-type-btn:hover {

  background: var(--bg-surface-hover);

}



.log-type-btn.active {

  background: var(--accent-active);

  color: var(--text-on-accent);

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

  color: var(--text-tertiary);

  font-weight: 500;

}



.log-service-filter .service-select {

  padding: 6px 12px;

  border: 1px solid var(--border-default);

  border-radius: 6px;

  background: var(--bg-surface);

  font-size: 13px;

  cursor: pointer;

  min-width: 150px;

}



.log-service-filter .service-select:focus {

  outline: none;

  border-color: #1976D2;

}



.log-container {

  background: var(--bg-surface);

  border-radius: 8px;

  border: 1px solid var(--border-default);

  overflow: visible;

  color: var(--text-secondary);

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

  color: var(--text-secondary);

}



.log-table th {

  background: var(--bg-surface-hover);

  padding: 10px 12px;

  text-align: left;

  font-weight: 600;

  border-bottom: 2px solid var(--border-default);

  white-space: nowrap;

  color: var(--text-secondary);

}



.log-table td {

  padding: 8px 12px;

  border-bottom: 1px solid var(--border-default);

  vertical-align: top;

  color: var(--text-secondary);

}



.log-table tr:hover {

  background: var(--bg-surface-hover);

}



.log-col-time {

  width: 150px;

  white-space: nowrap;

  color: var(--text-tertiary);

}



.log-col-level {

  width: 90px;

  white-space: nowrap;

}



.log-col-module {

  width: 220px;

  white-space: nowrap;

  color: var(--text-tertiary);

}



.log-col-content {

  word-break: break-all;

  min-width: 200px;

  color: var(--text-secondary);

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



.log-level-info { background: var(--accent); color: var(--text-on-accent); }

.log-level-warn { background: var(--warning); color: var(--text-on-accent); }

.log-level-error { background: var(--danger); color: var(--text-on-accent); }

.log-level-fatal { background: #B71C1C; color: var(--text-on-accent); }

.log-level-debug { background: var(--text-tertiary); color: var(--text-on-accent); }



.log-source {

  color: var(--text-tertiary);

  font-size: 12px;

  font-family: monospace;

}



/* 分页 */

.log-pagination {

  display: flex;

  align-items: center;

  justify-content: space-between;

  padding: 12px 16px;

  border-top: 1px solid var(--border-default);

  flex-wrap: wrap;

  gap: 8px;

}



.log-page-info {

  color: var(--text-tertiary);

  font-size: 13px;

}



.log-page-btns {

  display: flex;

  align-items: center;

  gap: 6px;

}



.page-btn {

  padding: 4px 10px;

  border: 1px solid var(--border-default);

  border-radius: 4px;

  background: var(--bg-surface);

  cursor: pointer;

  font-size: 12px;

}



.page-btn:hover:not(:disabled) {

  background: var(--bg-surface-hover);

}



.page-btn:disabled {

  opacity: 0.4;

  cursor: not-allowed;

}



.page-current {

  font-size: 13px;

  padding: 0 8px;

  color: var(--text-secondary);

}



.page-size-select {

  padding: 4px 8px;

  border: 1px solid var(--border-default);

  border-radius: 4px;

  font-size: 12px;

  cursor: pointer;

}



/* 加载和空状态 */

.loading-text, .empty-text {

  text-align: center;

  padding: 40px;

  color: var(--text-tertiary);

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

    border-bottom: 1px solid var(--border-default);

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

    color: var(--text-secondary);

  }



  .log-card-content {

    font-size: 13px;

    color: var(--text-secondary);

    word-break: break-all;

    margin-bottom: 6px;

  }



  .log-card-time {

    font-size: 11px;

    color: var(--text-tertiary);

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

  background: var(--bg-surface);

  border-radius: 12px;

  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);

  overflow: hidden;

}



.monitor-card-header {

  display: flex;

  align-items: center;

  gap: 10px;

  padding: 16px 20px;

  background: var(--accent-soft);

  color: var(--accent);

  border-bottom: 1px solid var(--border-color, var(--border-default));

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

  background: var(--bg-surface);

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

  color: var(--text-tertiary);

  margin-bottom: 6px;

}



.monitor-detail:last-child {

  margin-bottom: 0;

}



.fs-type {

  color: var(--text-secondary);

  font-size: 12px;

}



.core-usage {

  margin-top: 16px;

  border-top: 1px solid var(--border-default);

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

  color: var(--text-secondary);

  width: 45px;

}



.core-value {

  font-size: 11px;

  color: var(--text-tertiary);

  width: 40px;

  text-align: right;

}



.monitor-uptime {

  display: flex;

  align-items: center;

  gap: 8px;

  padding: 12px 16px;

  background: var(--bg-surface);

  border-radius: 8px;

  font-size: 14px;

}



.uptime-label {

  color: var(--text-tertiary);

}



.uptime-value {

  color: var(--text-secondary);

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

  border: 1px solid var(--border-color, var(--border-default));

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

  color: var(--text-secondary);

}



.text-error {

  color: #ef4444;

}



.thumb-service-detail {

  background: var(--card-bg, #1e1e2e);

  border-radius: 12px;

  padding: 16px 20px;

  margin-bottom: 24px;

  border: 1px solid var(--border-color, var(--border-default));

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

  border-bottom: 1px solid var(--border-color, var(--border-default));

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

  background: var(--success);

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

.auto-progress-box {
  margin: 12px 0;
  padding: 14px 16px;
  background: var(--bg-surface, #1a1d2e);
  border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
  border-radius: 10px;
}

.auto-progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
  font-size: 14px;
}

.auto-progress-title {
  font-weight: 600;
  color: var(--text-primary, #e2e8f0);
}

.auto-progress-count {
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary, #94a3b8);
}

.auto-progress-bar {
  width: 100%;
  height: 10px;
  background: rgba(255, 255, 255, 0.08);
  border-radius: 6px;
  overflow: hidden;
}

.auto-progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #10b981);
  border-radius: 6px;
  transition: width 0.4s ease;
}

.auto-progress-meta {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-secondary, #94a3b8);
}

.auto-progress-current {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 50%;
  margin-left: auto;
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

  border: 3px solid var(--border-color, var(--border-default));

  border-top-color: var(--accent);

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

  border: 1px solid var(--border-color, var(--border-default));

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

  background: var(--accent-soft);

  color: var(--accent);

  border-bottom: 1px solid var(--border-color, var(--border-default));

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

  color: var(--accent);

}



.svc-name-tag {

  font-size: 11px;

  padding: 2px 8px;

  border-radius: 4px;

  background: rgba(102, 126, 234, 0.15);

  color: var(--accent);

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

  background: var(--success);

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

  background: var(--accent);

  box-shadow: 0 0 6px rgba(59, 130, 246, 0.5);

  animation: pulse-dot 1s infinite;

}

.health-light.svc-unknown .light-dot {

  background: var(--text-tertiary);

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

.metric-value.svc-unknown { color: var(--text-secondary); }



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

  border-top: 1px solid var(--border-color, var(--border-default));

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

  background: var(--success);

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

.import-modal-title .modal-subtitle { margin: 4px 0 0; color: var(--text-secondary); font-size: 13px; }

.import-modal-body { overflow-y: auto; padding: 16px 20px; }

.import-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 14px; }

.scan-progress-inline { color: var(--text-tertiary); font-size: 13px; }

.import-results { padding: 0; }

.import-video-list { max-height: 46vh; overflow-y: auto; border: 1px solid var(--border-default); border-radius: 8px; }

.import-progress-inline { padding: 10px 0; color: var(--text-tertiary); font-size: 13px; }

.import-action-bar { display: flex; align-items: center; gap: 14px; border-top: 1px solid var(--border-default); padding: 14px 20px; background: var(--bg-surface); }

.import-action-bar .selected-count { color: var(--text-tertiary); font-size: 13px; }

.import-action-bar .action-btn.primary.large { margin-left: auto; }

/* 回收站卡片网格（替代旧 data-table） */
.trash-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.trash-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.trash-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}

.trash-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: var(--accent-soft);
  color: var(--accent);
  border-bottom: 1px solid var(--border-color, var(--border-default));
}

.trash-card-body {
  padding: 16px 20px;
}

.trash-type-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}
.trash-type-badge.type-video { background: rgba(96,165,250,0.14); color: #60a5fa; }
.trash-type-badge.type-gallery { background: rgba(168,85,247,0.14); color: #a855f7; }

.trash-time {
  font-size: 12px;
  color: var(--text-tertiary);
}

.trash-title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trash-meta {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: var(--text-secondary);
}

.trash-actions {
  display: flex;
  gap: 8px;
  padding-top: 4px;
  border-top: 1px solid var(--border-subtle);
}

@media (max-width: 640px) {
  .trash-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }
  .trash-card {
    padding: 12px;
  }
  .trash-actions {
    flex-wrap: wrap;
  }
  .trash-actions .btn {
    flex: 1;
    text-align: center;
  }
}

/* 资源库管理 - 移动端优化 */
@media (max-width: 768px) {
  /* 资源库 section header：标题和操作区换行 */
  .section-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 10px;
  }

  /* 操作按钮区域：自动换行，紧凑排列 */
  .header-actions {
    width: 100%;
    flex-wrap: wrap;
    gap: 8px;
  }

  /* 扫描按钮组：横向可滚动，避免竖排 */
  .scan-actions {
    display: flex;
    flex-wrap: nowrap;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    gap: 6px;
    scrollbar-width: none;
  }
  .scan-actions::-webkit-scrollbar { display: none; }

  /* 扫描按钮文字缩小 */
  .scan-actions .action-btn {
    font-size: 11px;
    padding: 6px 10px;
    white-space: nowrap;
    flex-shrink: 0;
  }

  /* 新建资源库按钮：固定宽度不压缩 */
  .header-actions > .action-btn.primary {
    flex-shrink: 0;
  }

  /* 扫描策略面板：手机端全宽、正常换行 */
  .scan-config-panel {
    width: 100%;
    max-width: 100%;
    margin-left: 0;
  }

  /* 资源库卡片网格：单列 */
  .library-grid {
    grid-template-columns: 1fr;
    gap: 14px;
  }

  /* 卡片操作按钮：2列等宽，更紧凑 */
  .library-card-actions {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 7px;
    padding: 10px 14px;
  }

  .library-card-actions .action-btn {
    flex: none;
    min-width: unset;
    padding: 8px 4px;
    font-size: 12px;
    justify-content: center;
  }

  /* 统计标签：允许换行 */
  .library-stats {
    flex-wrap: wrap;
    gap: 5px;
  }

  .stat-pill {
    font-size: 11px;
    padding: 3px 8px;
  }
}

</style>

