<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import { useUserStore } from '../stores/userStore'
import api from '../api'

const router = useRouter()
const videoStore = useVideoStore()
const userStore = useUserStore()

// 视频库列表
const libraries = ref<any[]>([])
const selectedLibraryId = ref<number | null>(null)
const isLoadingLibraries = ref(true)

// 获取视频库列表
const fetchLibraries = async () => {
  try {
    console.log('开始获取视频库列表...')
    isLoadingLibraries.value = true
    const res = await api.get('/api/user/libraries') as any
    console.log('视频库 API 响应:', res)
    
    if (res.success) {
      libraries.value = res.data || []
      console.log('获取到的视频库数量:', libraries.value.length)
      
      // 默认选择第一个有写权限的视频库
      const writableLib = libraries.value.find((lib: any) => lib.access_level === 'full' || lib.access_level === 'write')
      if (writableLib) {
        selectedLibraryId.value = writableLib.id
        console.log('✓ 自动选择视频库:', writableLib.name, 'ID:', writableLib.id)
      } else {
        console.warn('没有找到有写权限的视频库')
      }
    } else {
      console.error('获取视频库失败:', res.message)
    }
  } catch (error) {
    console.error('获取视频库列表失败:', error)
  } finally {
    isLoadingLibraries.value = false
    console.log('✓ 视频库加载完成')
  }
}

onMounted(() => {
  fetchLibraries()
})

// 上传状态
const isDragging = ref(false)
const isUploading = ref(false)
const isProcessing = ref(false)  // 文件传输完成，等待服务器处理
const uploadProgress = ref(0)
const uploadError = ref('')
const uploadedVideo = ref<any>(null)
const selectedFiles = ref<File[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const isMultipleFiles = computed(() => selectedFiles.value.length > 1)

// 错误弹窗
const showErrorModal = ref(false)
const errorModalMessage = ref('')
const errorModalTitle = ref('上传失败')

const showErrorDialog = (title: string, message: string) => {
  errorModalTitle.value = title
  errorModalMessage.value = message
  showErrorModal.value = true
}

const closeErrorModal = () => {
  showErrorModal.value = false
}

// 视频信息表单
const videoForm = ref({
  title: '',
  description: '',
  tags: [] as number[]
})

// 支持的文件格式
const supportedFormats = ['.mp4', '.avi', '.mkv', '.mov', '.webm', '.flv', '.wmv']
const maxFileSize = 2 * 1024 * 1024 * 1024 // 2GB

// 格式化文件大小
const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(2)} ${units[unitIndex]}`
}

// 处理拖拽进入
const handleDragEnter = (e: DragEvent) => {
  e.preventDefault()
  isDragging.value = true
}

// 处理拖拽离开
const handleDragLeave = (e: DragEvent) => {
  e.preventDefault()
  isDragging.value = false
}

// 处理拖拽悬停
const handleDragOver = (e: DragEvent) => {
  e.preventDefault()
}

// 处理文件拖放
const handleDrop = (e: DragEvent) => {
  e.preventDefault()
  isDragging.value = false

  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    handleFiles(Array.from(files))
  }
}

// 处理文件选择
const handleFileSelect = (e: Event) => {
  console.log('【文件选择】事件触发')
  const input = e.target as HTMLInputElement
  
  if (!input.files || input.files.length === 0) {
    console.log('【文件选择】没有选择文件')
    return
  }
  
  console.log(`【文件选择】选择了 ${input.files.length} 个文件`)
  console.log(`【文件选择】当前状态: isLoadingLibraries=${isLoadingLibraries.value}, selectedLibraryId=${selectedLibraryId.value}`)
  console.log(`【文件选择】文件名列表:`, Array.from(input.files).map(f => f.name))
  
  // 如果视频库还在加载中，提示用户等待
  if (isLoadingLibraries.value) {
    showToast('视频库列表正在加载中，请稍后再试')
    console.log('【文件选择】视频库正在加载，显示错误提示')
    // 清空文件选择
    input.value = ''
    return
  }
  
  console.log(`【文件选择】视频库已选择: ${selectedLibraryId.value}，准备处理文件`)
  
  try {
    const files = Array.from(input.files)
    handleFiles(files)
  } catch (error) {
    console.error('【文件选择】处理文件时发生错误:', error)
    showToast('处理文件时发生错误，请重试')
  }
}

// 验证文件
const validateFile = (file: File): string | null => {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase()
  if (!supportedFormats.includes(ext)) {
    return `不支持的文件格式：${file.name}`
  }
  if (file.size > maxFileSize) {
    return `文件 ${file.name} 大小超过限制，最大支持 ${formatFileSize(maxFileSize)}`
  }
  return null
}

// 处理文件列表
const handleFiles = async (files: File[]) => {
  console.log('【handleFiles】=== 开始 ===')
  console.log('【handleFiles】文件数量:', files.length)
  console.log('【handleFiles】当前视频库 ID:', selectedLibraryId.value)
  console.log('【handleFiles】文件名列表:', files.map(f => f.name))
  
  try {
    // 验证视频库选择（先检查，避免用户浪费时间）
    if (!selectedLibraryId.value) {
      showToast('请先选择目标视频库')
      console.error('【handleFiles】视频库未选择')
      // 重置文件输入框，允许重新选择
      if (fileInput.value) {
        fileInput.value.value = ''
      }
      return
    }
    
    // 验证所有文件
    const errors: string[] = []
    const validFiles: File[] = []
    
    for (const file of files) {
      const error = validateFile(file)
      if (error) {
        errors.push(error)
        console.error('【handleFiles】文件验证失败:', error)
      } else {
        validFiles.push(file)
      }
    }
    
    // 如果有格式错误，用 Toast 提示
    if (errors.length > 0) {
      // 显示第一个错误，并告知有多少个文件格式不符合
      const errorMsg = errors.length === 1 
        ? errors[0] 
        : `有 ${errors.length} 个文件格式不支持，仅支持 MP4、AVI、MKV、MOV、WebM、FLV、WMV 格式`
      showToast(errorMsg)
      console.error('【handleFiles】文件验证错误:', errors)
      
      // 如果没有有效文件，直接返回
      if (validFiles.length === 0) {
        // 重置文件输入框，允许重新选择
        if (fileInput.value) {
          fileInput.value.value = ''
        }
        return
      }
      
      // 如果有部分有效文件，继续处理有效文件
      console.log('【handleFiles】部分文件有效，继续处理:', validFiles.length, '个文件')
    }
    
    // 清空之前的错误信息
    uploadError.value = ''
    
    console.log('【handleFiles】准备设置 selectedFiles，当前值:', selectedFiles.value.length)
    
    // 保存选中的文件（使用 Array.from 确保是真正的数组）
    selectedFiles.value = Array.from(validFiles)
    
    console.log('【handleFiles】已设置 selectedFiles，新值:', selectedFiles.value.length)
    
    // 强制触发响应式更新
    await nextTick()
    
    console.log('【handleFiles】nextTick 完成')
    console.log('【handleFiles】✓ 文件已保存到 selectedFiles:', selectedFiles.value.length)
    console.log('【handleFiles】✓ selectedFiles 内容:', selectedFiles.value.map(f => f.name))
    
    // 如果是单文件，设置默认标题
    if (validFiles.length === 1) {
      videoForm.value.title = validFiles[0].name.replace(/\.[^/.]+$/, '')
      console.log('【handleFiles】单文件模式，设置默认标题:', videoForm.value.title)
    } else {
      // 多文件时清空标题和描述
      videoForm.value.title = ''
      videoForm.value.description = ''
      console.log('【handleFiles】多文件模式，已清空标题和描述')
    }
    
    console.log('【handleFiles】✓ 当前状态:')
    console.log('【handleFiles】  - isUploading:', isUploading.value)
    console.log('【handleFiles】  - uploadedVideo:', !!uploadedVideo.value)
    console.log('【handleFiles】  - selectedFiles.length:', selectedFiles.value.length)
    console.log('【handleFiles】  - 表单应该显示:', !isUploading.value && !uploadedVideo.value && selectedFiles.value.length > 0)
    console.log('【handleFiles】=== 完成 ===')
  } catch (error) {
    console.error('【handleFiles】发生错误:', error)
    showToast('处理文件时发生错误: ' + (error instanceof Error ? error.message : '未知错误'))
    // 重置文件输入框，允许重新选择
    if (fileInput.value) {
      fileInput.value.value = ''
    }
  }
}

// 开始上传
const startUpload = async () => {
  if (selectedFiles.value.length === 0) {
    showToast('请先选择文件')
    return
  }
  
  uploadError.value = ''
  isUploading.value = true
  isProcessing.value = false
  uploadProgress.value = 0
  
  const totalFiles = selectedFiles.value.length
  let uploadedCount = 0
  const failedFiles: { name: string; reason: string }[] = []
  
  try {
    for (const file of selectedFiles.value) {
      const formData = new FormData()
      formData.append('video', file)
      
      // 单文件时使用表单标题，多文件时使用文件名
      if (totalFiles === 1) {
        formData.append('title', videoForm.value.title || file.name.replace(/\.[^/.]+$/, ''))
        formData.append('description', videoForm.value.description)
      } else {
        formData.append('title', file.name.replace(/\.[^/.]+$/, ''))
      }
      
      if (selectedLibraryId.value) {
        formData.append('library_id', selectedLibraryId.value.toString())
      }
      
      try {
        const response = await api.post('/api/upload', formData, {
          headers: {
            'Content-Type': 'multipart/form-data'
          },
          timeout: 0,  // 上传文件不设超时限制
          onUploadProgress: (progressEvent: any) => {
            if (progressEvent.total) {
              const fileProgress = progressEvent.loaded / progressEvent.total
              // 当前文件进度在总进度中的占比（最多到95%，留5%给服务器处理）
              const rawProgress = ((uploadedCount + fileProgress) / totalFiles) * 95
              uploadProgress.value = Math.min(rawProgress, 95)
              // 文件传输完成，进入服务器处理阶段
              if (fileProgress >= 1) {
                isProcessing.value = true
              }
            }
          }
        }) as any
        
        isProcessing.value = false
        
        if (response.success) {
          uploadedCount++
          uploadProgress.value = (uploadedCount / totalFiles) * 95
        } else {
          const reason = response.message || '未知错误'
          failedFiles.push({ name: file.name, reason })
          console.error(`上传失败 [${file.name}]:`, reason)
        }
      } catch (error: any) {
        isProcessing.value = false
        let reason = '网络错误'
        if (error?.response?.status === 413) {
          reason = '文件过大（超过服务器限制）'
        } else if (error?.response?.status === 403) {
          reason = '无权限上传到该视频库'
        } else if (error?.response?.status === 409) {
          reason = '该视频已存在'
        } else if (error?.response?.data?.message) {
          reason = error.response.data.message
        } else if (error?.message) {
          reason = error.message
        }
        failedFiles.push({ name: file.name, reason })
        console.error(`上传异常 [${file.name}]:`, error?.response?.data || error?.message || error)
      }
    }
    
    // 所有文件上传完成
    uploadProgress.value = 100
    isProcessing.value = false
    
    if (failedFiles.length === 0) {
      // 全部成功
      uploadedVideo.value = { count: totalFiles }
      setTimeout(async () => {
        // 刷新视频列表
        await videoStore.fetchVideos(true)
        router.push('/')
      }, 1500)
    } else if (uploadedCount > 0) {
      // 部分成功 - 弹窗提示
      const failList = failedFiles.map(f => `• ${f.name}：${f.reason}`).join('\n')
      showErrorDialog(
        '部分文件上传失败',
        `成功上传 ${uploadedCount} 个，失败 ${failedFiles.length} 个：\n\n${failList}`
      )
    } else {
      // 全部失败 - 弹窗提示
      if (failedFiles.length === 1) {
        showErrorDialog('上传失败', `${failedFiles[0].name}\n\n原因：${failedFiles[0].reason}`)
      } else {
        const failList = failedFiles.map(f => `• ${f.name}：${f.reason}`).join('\n')
        showErrorDialog('上传失败', `全部 ${failedFiles.length} 个文件上传失败：\n\n${failList}`)
      }
    }
  } catch (error: any) {
    isProcessing.value = false
    showErrorDialog('上传失败', error.message || '上传过程中发生未知错误，请重试')
  } finally {
    isUploading.value = false
  }
}

// 获取标签列表
const availableTags = computed(() => videoStore.tags)

// 有写权限的视频库
const writableLibraries = computed(() => {
  return libraries.value.filter((lib: any) => 
    lib.access_level === 'full' || lib.access_level === 'write'
  )
})

// 切换标签选择
const toggleTag = (tagId: number) => {
  const index = videoForm.value.tags.indexOf(tagId)
  if (index > -1) {
    videoForm.value.tags.splice(index, 1)
  } else {
    videoForm.value.tags.push(tagId)
  }
}

// 处理上传区域点击
const handleUploadZoneClick = () => {
  // 清除之前的错误
  uploadError.value = ''
  
  // 确保文件输入元素存在，直接触发文件选择
  // 视频库的检查放到 handleFileSelect 中进行
  if (fileInput.value) {
    fileInput.value.click()
  } else {
    console.error('文件输入元素未找到')
  }
}

// Toast 提示
const toastMessage = ref('')
const showToastFlag = ref(false)
const showToast = (message: string) => {
  toastMessage.value = message
  showToastFlag.value = true
  setTimeout(() => {
    showToastFlag.value = false
  }, 3000)
}

// 清除错误并重置文件选择
const clearError = () => {
  uploadError.value = ''
  showErrorModal.value = false
  selectedFiles.value = []
  uploadedVideo.value = null
  isUploading.value = false
  isProcessing.value = false
  uploadProgress.value = 0
  // 重置文件输入框，允许重新选择相同文件
  if (fileInput.value) {
    fileInput.value.value = ''
  }
}
</script>

<template>
  <div class="upload-page">
    <div class="upload-container">
      <h1 class="page-title">上传视频</h1>
      
      <!-- 视频库选择 - 始终显示在最上方 -->
      <div v-if="!isUploading && !uploadedVideo" class="library-section" :class="{ 'has-error': !selectedLibraryId }">
        <h3 class="section-title">
          <span class="required-mark">*</span> 选择目标视频库
          <span v-if="!selectedLibraryId" class="hint-text">（必选）</span>
        </h3>
        <div class="library-grid">
          <div
            v-for="lib in writableLibraries"
            :key="lib.id"
            class="library-card"
            :class="{ selected: selectedLibraryId === lib.id }"
            @click="selectedLibraryId = lib.id"
          >
            <div class="library-icon">📁</div>
            <div class="library-name">{{ lib.name }}</div>
            <div class="library-check" v-if="selectedLibraryId === lib.id">✓</div>
          </div>
        </div>
        <p v-if="writableLibraries.length === 0" class="no-library-hint">
          暂无可用的视频库，请联系管理员
        </p>
      </div>

      <!-- 上传区域 -->
      <div
        v-if="!isUploading && !uploadedVideo && selectedFiles.length === 0"
        class="upload-zone"
        :class="{ dragging: isDragging, disabled: !selectedLibraryId || isLoadingLibraries }"
        @dragenter="handleDragEnter"
        @dragleave="handleDragLeave"
        @dragover="handleDragOver"
        @drop="handleDrop"
        @click="handleUploadZoneClick"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".mp4,.avi,.mkv,.mov,.webm,.flv,.wmv"
          multiple
          class="hidden-file-input"
          @change="handleFileSelect"
          @click.stop
        />
        <div class="upload-icon">
          <svg v-if="isLoadingLibraries" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" class="spin-animation">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 6v6l4 2"/>
          </svg>
          <svg v-else width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
        </div>
        <p class="upload-text">
          <span v-if="isLoadingLibraries">正在加载视频库...</span>
          <span v-else><span class="highlight">点击选择文件</span> 或拖拽视频到此处</span>
        </p>
        <p class="upload-hint" v-if="!isLoadingLibraries">
          支持格式：MP4、AVI、MKV、MOV、WebM<br/>
          单个文件最大 {{ formatFileSize(maxFileSize) }}<br/>
          <span class="desktop-hint">💡 按住 Ctrl 或 ⌘ 键可选择多个文件</span>
          <span class="mobile-hint">📱 移动端：点击右上角菜单 → 选择多个文件</span>
        </p>
      </div>
      
      <!-- 已选择的文件列表 -->
      <div v-if="!isUploading && !uploadedVideo && selectedFiles.length > 0" class="selected-files">
        <div class="files-header">
          <h3>已选择 {{ selectedFiles.length }} 个文件</h3>
          <button class="clear-btn" @click="selectedFiles = []">清空</button>
        </div>
        <div class="files-list">
          <div v-for="(file, index) in selectedFiles" :key="index" class="file-item">
            <div class="file-icon">🎬</div>
            <div class="file-info">
              <div class="file-name">{{ file.name }}</div>
              <div class="file-size">{{ formatFileSize(file.size) }}</div>
            </div>
          </div>
        </div>
      </div>
      
      <!-- 上传进度 -->
      <div v-if="isUploading" class="upload-progress">
        <div class="progress-header">
          <h3>{{ isProcessing ? '服务器处理中...' : '正在上传...' }}</h3>
          <span class="progress-percent">{{ Math.round(uploadProgress) }}%</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :class="{ processing: isProcessing }" :style="{ width: uploadProgress + '%' }"></div>
        </div>
        <p class="progress-hint">{{ isProcessing ? '文件已传输完成，等待服务器处理，请稍候...' : '请勿关闭页面' }}</p>
      </div>
      
      <!-- 上传成功 -->
      <div v-if="uploadedVideo" class="upload-success">
        <div class="success-icon">✓</div>
        <h3>上传成功！</h3>
        <p v-if="uploadedVideo.count">成功上传 {{ uploadedVideo.count }} 个视频</p>
        <p v-else>正在跳转到视频页面...</p>
      </div>
      
      <!-- 错误提示 - 仅用于非格式错误的其他错误（保留内嵌样式作为备用） -->
      <!-- <div v-if="uploadError && !isUploading && !uploadedVideo" class="upload-error"> ... </div> -->
      
      <!-- Toast 提示 -->
      <div v-if="showToastFlag" class="toast">
        {{ toastMessage }}
      </div>

      <!-- 上传失败弹窗 -->
      <Teleport to="body">
        <div v-if="showErrorModal" class="error-modal-overlay" @click.self="closeErrorModal">
          <div class="error-modal">
            <div class="error-modal-header">
              <div class="error-modal-icon">✕</div>
              <h3>{{ errorModalTitle }}</h3>
            </div>
            <div class="error-modal-body">
              <p v-for="(line, i) in errorModalMessage.split('\n')" :key="i" :class="{ 'error-line': line.startsWith('•'), 'empty-line': line === '' }">
                {{ line || '\u00A0' }}
              </p>
            </div>
            <div class="error-modal-footer">
              <button class="error-modal-retry" @click="clearError()">重新上传</button>
              <button class="error-modal-close" @click="closeErrorModal">关闭</button>
            </div>
          </div>
        </div>
      </Teleport>
      
      <!-- 视频信息表单 -->
      <div v-if="!isUploading && !uploadedVideo && selectedFiles.length > 0" class="video-form">
        <h3>视频信息</h3>
        <p class="form-hint">
          <span v-if="isMultipleFiles">多文件上传模式：使用文件名作为标题</span>
          <span v-else>标题和描述为可选项</span>
        </p>
        
        <!-- 单文件时显示标题和描述 -->
        <template v-if="!isMultipleFiles">
          <div class="form-group">
            <label>标题</label>
            <input 
              v-model="videoForm.title" 
              type="text" 
              placeholder="输入视频标题"
            />
          </div>
          <div class="form-group">
            <label>描述</label>
            <textarea 
              v-model="videoForm.description" 
              rows="3" 
              placeholder="输入视频描述"
            ></textarea>
          </div>
          <div class="form-group">
            <label>标签</label>
            <div class="tag-selector">
              <span 
                v-for="tag in availableTags" 
                :key="tag.id"
                class="tag-option"
                :class="{ selected: videoForm.tags.includes(tag.id) }"
                @click="toggleTag(tag.id)"
              >
                {{ tag.name }}
              </span>
            </div>
          </div>
        </template>
        
        <!-- 上传按钮 -->
        <div class="form-actions">
          <button 
            class="upload-btn"
            @click="startUpload"
          >
            {{ isMultipleFiles ? `上传 ${selectedFiles.length} 个文件` : '开始上传' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.upload-page {
  min-height: 100vh;
  background: #0f0f0f;
  padding: 40px 20px;
}

.upload-container {
  max-width: 800px;
  margin: 0 auto;
}

.page-title {
  color: #fff;
  font-size: 28px;
  margin-bottom: 32px;
  text-align: center;
}

/* 视频库选择 */
.library-section {
  margin-bottom: 24px;
  padding: 20px;
  background: #1a1a1a;
  border-radius: 16px;
  border: 2px solid transparent;
  transition: border-color 0.3s ease;
}

.library-section.has-error {
  border-color: #ff4d4f;
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% {
    border-color: #ff4d4f;
  }
  50% {
    border-color: #ff8080;
  }
}

.section-title {
  color: #fff;
  font-size: 18px;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.required-mark {
  color: #ff4d4f;
  font-size: 20px;
}

.hint-text {
  color: #ff4d4f;
  font-size: 14px;
  font-weight: normal;
}

.library-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}

.library-card {
  background: #1a1a1a;
  border: 2px solid #333;
  border-radius: 12px;
  padding: 20px 16px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
  position: relative;
}

.library-card:hover {
  border-color: #667eea;
  transform: translateY(-2px);
}

.library-card.selected {
  border-color: #667eea;
  background: linear-gradient(135deg, rgba(102, 126, 234, 0.1) 0%, rgba(118, 75, 162, 0.1) 100%);
}

.library-icon {
  font-size: 32px;
  margin-bottom: 8px;
}

.library-name {
  color: #fff;
  font-size: 14px;
  font-weight: 500;
}

.library-check {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 24px;
  height: 24px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 14px;
}

.no-library-hint {
  color: #888;
  text-align: center;
  padding: 20px;
}

/* 上传区域 */
.upload-zone {
  background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
  border: 2px dashed #667eea;
  border-radius: 16px;
  padding: 60px 40px;
  text-align: center;
  cursor: pointer;
  transition: all 0.3s ease;
}

.upload-zone:hover,
.upload-zone.dragging {
  background: linear-gradient(135deg, #1f1f3a 0%, #1a2748 100%);
  border-color: #764ba2;
  transform: translateY(-2px);
}

.upload-zone.disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.upload-zone.disabled:hover {
  transform: none;
}

/* 旋转动画 */
.spin-animation {
  animation: spin 1.5s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}

.upload-icon {
  color: #667eea;
  margin-bottom: 20px;
}

.upload-text {
  color: #fff;
  font-size: 18px;
  margin-bottom: 12px;
}

.upload-text .highlight {
  color: #667eea;
  font-weight: 600;
}

.upload-hint {
  color: #888;
  font-size: 14px;
  line-height: 1.6;
}

.mobile-hint {
  display: none;
  color: #667eea;
  font-size: 12px;
  margin-top: 8px;
}

.desktop-hint {
  display: block;
  color: #667eea;
  font-size: 12px;
  margin-top: 8px;
}

/* 移动端显示移动提示，隐藏桌面提示 */
@media (max-width: 768px) {
  .mobile-hint {
    display: block;
  }
  .desktop-hint {
    display: none;
  }
}

/* 隐藏文件输入框 - 使用 opacity 和 position 确保移动端兼容 */
.hidden-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* 上传进度 */
.upload-progress {
  background: #1a1a1a;
  border-radius: 16px;
  padding: 40px;
  text-align: center;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}

.progress-header h3 {
  color: #fff;
  margin: 0;
}

.progress-percent {
  color: #667eea;
  font-size: 24px;
  font-weight: 700;
}

.progress-bar {
  height: 8px;
  background: #333;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 16px;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
  border-radius: 4px;
  transition: width 0.3s ease;
}

.progress-hint {
  color: #888;
  font-size: 14px;
}

/* 上传成功 */
.upload-success {
  background: #1a1a1a;
  border-radius: 16px;
  padding: 60px 40px;
  text-align: center;
}

.success-icon {
  width: 80px;
  height: 80px;
  background: linear-gradient(135deg, #4CAF50 0%, #45a049 100%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 40px;
  margin: 0 auto 24px;
}

.upload-success h3 {
  color: #fff;
  font-size: 24px;
  margin-bottom: 12px;
}

.upload-success p {
  color: #888;
}

/* 错误提示 */
.upload-error {
  background: #1a1a1a;
  border-radius: 16px;
  padding: 40px;
  text-align: center;
}

.error-icon {
  width: 64px;
  height: 64px;
  background: #ff4d4f;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 32px;
  margin: 0 auto 20px;
}

.upload-error p {
  color: #ff4d4f;
  margin-bottom: 20px;
}

.retry-btn {
  padding: 12px 32px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  cursor: pointer;
  transition: opacity 0.3s ease;
}

.retry-btn:hover {
  opacity: 0.9;
}

/* 视频信息表单 */
.video-form {
  background: #1a1a1a;
  border-radius: 16px;
  padding: 32px;
  margin-top: 24px;
}

.video-form h3 {
  color: #fff;
  font-size: 18px;
  margin-bottom: 8px;
}

.form-hint {
  color: #666;
  font-size: 13px;
  margin-bottom: 24px;
}

.form-group {
  margin-bottom: 20px;
}

.form-group label {
  display: block;
  color: #888;
  font-size: 14px;
  margin-bottom: 8px;
}

.form-group input,
.form-group textarea {
  width: 100%;
  padding: 12px 16px;
  background: #0f0f0f;
  border: 1px solid #333;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  transition: border-color 0.3s ease;
  box-sizing: border-box;
}

.form-group input:focus,
.form-group textarea:focus {
  outline: none;
  border-color: #667eea;
}

.form-group textarea {
  resize: vertical;
  min-height: 80px;
}

/* 标签选择器 */
.tag-selector {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-option {
  padding: 6px 14px;
  background: #0f0f0f;
  border: 1px solid #333;
  border-radius: 16px;
  color: #888;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.tag-option:hover {
  border-color: #667eea;
  color: #fff;
}

.tag-option.selected {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-color: transparent;
  color: #fff;
}

/* 已选择文件列表 */
.selected-files {
  background: #1a1a1a;
  border-radius: 16px;
  padding: 24px;
  margin-bottom: 24px;
}

.files-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.files-header h3 {
  color: #fff;
  font-size: 18px;
  margin: 0;
}

.clear-btn {
  padding: 6px 16px;
  background: transparent;
  border: 1px solid #666;
  border-radius: 6px;
  color: #888;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.3s ease;
}

.clear-btn:hover {
  border-color: #ff4d4f;
  color: #ff4d4f;
}

.files-list {
  max-height: 300px;
  overflow-y: auto;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px;
  background: #0f0f0f;
  border-radius: 8px;
  margin-bottom: 8px;
}

.file-icon {
  font-size: 24px;
}

.file-info {
  flex: 1;
}

.file-name {
  color: #fff;
  font-size: 14px;
  margin-bottom: 4px;
}

.file-size {
  color: #666;
  font-size: 12px;
}

/* 表单操作按钮 */
.form-actions {
  margin-top: 24px;
}

.upload-btn {
  width: 100%;
  padding: 14px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.3s ease;
}

.upload-btn:hover:not(:disabled) {
  opacity: 0.9;
  transform: translateY(-2px);
}

.upload-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Toast 提示 */
.toast {
  position: fixed;
  top: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(255, 77, 79, 0.95);
  color: #fff;
  padding: 12px 24px;
  border-radius: 8px;
  font-size: 14px;
  z-index: 1000;
  animation: toastSlideIn 0.3s ease;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  max-width: 90%;
  text-align: center;
}

@keyframes toastSlideIn {
  from {
    opacity: 0;
    transform: translateX(-50%) translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateX(-50%) translateY(0);
  }
}

/* 进度条处理中状态（闪烁动画） */
.progress-fill.processing {
  background: linear-gradient(90deg, #667eea 0%, #764ba2 50%, #667eea 100%);
  background-size: 200% 100%;
  animation: progressShimmer 1.5s ease infinite;
}

@keyframes progressShimmer {
  0% { background-position: 100% 0; }
  100% { background-position: -100% 0; }
}

/* 错误弹窗遮罩 */
.error-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.65);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
  animation: overlayFadeIn 0.2s ease;
  padding: 20px;
}

@keyframes overlayFadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

/* 错误弹窗主体 */
.error-modal {
  background: #1e1e2e;
  border: 1px solid #3a3a5c;
  border-radius: 20px;
  width: 100%;
  max-width: 480px;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.6);
  animation: modalSlideIn 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
  overflow: hidden;
}

@keyframes modalSlideIn {
  from { opacity: 0; transform: scale(0.9) translateY(20px); }
  to { opacity: 1; transform: scale(1) translateY(0); }
}

.error-modal-header {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 36px 32px 20px;
  gap: 16px;
}

.error-modal-icon {
  width: 64px;
  height: 64px;
  background: linear-gradient(135deg, #ff4d4f 0%, #cf1322 100%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: 28px;
  font-weight: bold;
  box-shadow: 0 8px 24px rgba(255, 77, 79, 0.35);
}

.error-modal-header h3 {
  color: #fff;
  font-size: 20px;
  margin: 0;
  font-weight: 600;
}

.error-modal-body {
  padding: 0 32px 24px;
  max-height: 280px;
  overflow-y: auto;
}

.error-modal-body p {
  color: #aaa;
  font-size: 14px;
  line-height: 1.7;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}

.error-modal-body p.error-line {
  color: #ff8080;
  background: rgba(255, 77, 79, 0.08);
  border-radius: 6px;
  padding: 4px 8px;
  margin: 2px 0;
}

.error-modal-body p.empty-line {
  height: 8px;
}

.error-modal-footer {
  display: flex;
  gap: 12px;
  padding: 0 32px 28px;
}

.error-modal-retry {
  flex: 1;
  padding: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff;
  border: none;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.error-modal-retry:hover {
  opacity: 0.88;
}

.error-modal-close {
  flex: 1;
  padding: 12px;
  background: transparent;
  color: #888;
  border: 1px solid #444;
  border-radius: 10px;
  font-size: 15px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.error-modal-close:hover {
  border-color: #666;
  color: #ccc;
}

/* 响应式 - 弹窗 */
@media (max-width: 768px) {
  .error-modal {
    border-radius: 16px;
  }
  .error-modal-header {
    padding: 28px 24px 16px;
  }
  .error-modal-body {
    padding: 0 24px 20px;
  }
  .error-modal-footer {
    padding: 0 24px 24px;
  }
  .upload-page {
    padding: 20px 16px;
  }
  
  .page-title {
    font-size: 22px;
  }
  
  .upload-zone {
    padding: 40px 20px;
  }
  
  .upload-text {
    font-size: 16px;
  }
  
  .video-form {
    padding: 20px;
  }
  
  .toast {
    top: 60px;
    padding: 10px 16px;
    font-size: 13px;
  }
}
</style>
