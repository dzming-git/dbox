<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useVideoStore } from '../stores/videoStore'
import { useUserStore } from '../stores/userStore'
import api from '../api'

const router = useRouter()
const videoStore = useVideoStore()
const userStore = useUserStore()

// 视频集列表
const libraries = ref<any[]>([])
const selectedLibraryId = ref<number | null>(null)

// 获取视频集列表
const fetchLibraries = async () => {
  try {
    const res = await api.get('/api/libraries') as any
    if (res.success) {
      libraries.value = res.data || []
      // 默认选择第一个有写权限的视频集
      const writableLib = libraries.value.find((lib: any) => lib.access_level === 'full' || lib.access_level === 'write')
      if (writableLib) {
        selectedLibraryId.value = writableLib.id
      }
    }
  } catch (error) {
    console.error('获取视频集列表失败:', error)
  }
}

onMounted(() => {
  fetchLibraries()
})

// 上传状态
const isDragging = ref(false)
const isUploading = ref(false)
const uploadProgress = ref(0)
const uploadError = ref('')
const uploadedVideo = ref<any>(null)

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
    handleFile(files[0])
  }
}

// 处理文件选择
const handleFileSelect = (e: Event) => {
  const input = e.target as HTMLInputElement
  if (input.files && input.files.length > 0) {
    handleFile(input.files[0])
  }
}

// 验证文件
const validateFile = (file: File): string | null => {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase()
  if (!supportedFormats.includes(ext)) {
    return `不支持的文件格式，请上传 ${supportedFormats.join(', ')} 格式的视频`
  }
  if (file.size > maxFileSize) {
    return `文件大小超过限制，最大支持 ${formatFileSize(maxFileSize)}`
  }
  // 验证视频集选择
  if (!selectedLibraryId.value) {
    return '请选择上传到的视频集'
  }
  return null
}

// 处理文件上传
const handleFile = async (file: File) => {
  const error = validateFile(file)
  if (error) {
    uploadError.value = error
    return
  }
  
  uploadError.value = ''
  isUploading.value = true
  uploadProgress.value = 0
  
  // 设置默认标题
  videoForm.value.title = file.name.replace(/\.[^/.]+$/, '')
  
  try {
    const formData = new FormData()
    formData.append('video', file)
    formData.append('title', videoForm.value.title)
    if (selectedLibraryId.value) {
      formData.append('library_id', selectedLibraryId.value.toString())
    }
    
    // 模拟上传进度
    const progressInterval = setInterval(() => {
      if (uploadProgress.value < 90) {
        uploadProgress.value += Math.random() * 10
      }
    }, 500)
    
    const response = await api.post('/api/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data'
      }
    }) as any
    
    clearInterval(progressInterval)
    uploadProgress.value = 100
    
    if (response.success) {
      uploadedVideo.value = response.video
      // 延迟后跳转到视频详情页
      setTimeout(() => {
        router.push(`/video/${response.video.hash}`)
      }, 1000)
    } else {
      uploadError.value = response.message || '上传失败'
    }
  } catch (error: any) {
    uploadError.value = error.message || '上传失败，请重试'
  } finally {
    isUploading.value = false
  }
}

// 获取标签列表
const availableTags = computed(() => videoStore.tags)

// 切换标签选择
const toggleTag = (tagId: number) => {
  const index = videoForm.value.tags.indexOf(tagId)
  if (index > -1) {
    videoForm.value.tags.splice(index, 1)
  } else {
    videoForm.value.tags.push(tagId)
  }
}
</script>

<template>
  <div class="upload-page">
    <div class="upload-container">
      <h1 class="page-title">上传视频</h1>
      
      <!-- 上传区域 -->
      <div
        v-if="!isUploading && !uploadedVideo"
        class="upload-zone"
        :class="{ dragging: isDragging }"
        @dragenter="handleDragEnter"
        @dragleave="handleDragLeave"
        @dragover="handleDragOver"
        @drop="handleDrop"
        @click="$refs.fileInput?.click()"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".mp4,.avi,.mkv,.mov,.webm,.flv,.wmv"
          style="display: none"
          @change="handleFileSelect"
        />
        <div class="upload-icon">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="17 8 12 3 7 8"/>
            <line x1="12" y1="3" x2="12" y2="15"/>
          </svg>
        </div>
        <p class="upload-text">
          <span class="highlight">点击选择文件</span> 或拖拽视频到此处
        </p>
        <p class="upload-hint">
          支持格式：MP4、AVI、MKV、MOV、WebM<br/>
          单个文件最大 {{ formatFileSize(maxFileSize) }}
        </p>
      </div>
      
      <!-- 上传进度 -->
      <div v-if="isUploading" class="upload-progress">
        <div class="progress-header">
          <h3>正在上传...</h3>
          <span class="progress-percent">{{ Math.round(uploadProgress) }}%</span>
        </div>
        <div class="progress-bar">
          <div class="progress-fill" :style="{ width: uploadProgress + '%' }"></div>
        </div>
        <p class="progress-hint">请勿关闭页面</p>
      </div>
      
      <!-- 上传成功 -->
      <div v-if="uploadedVideo" class="upload-success">
        <div class="success-icon">✓</div>
        <h3>上传成功！</h3>
        <p>正在跳转到视频页面...</p>
      </div>
      
      <!-- 错误提示 -->
      <div v-if="uploadError" class="upload-error">
        <div class="error-icon">✕</div>
        <p>{{ uploadError }}</p>
        <button class="retry-btn" @click="uploadError = ''">重试</button>
      </div>
      
      <!-- 视频信息表单（可选） -->
      <div v-if="!isUploading && !uploadedVideo" class="video-form">
        <h3>视频信息（可选）</h3>
        
        <!-- 视频集选择 -->
        <div class="form-group">
          <label>视频集 *</label>
          <select v-model="selectedLibraryId" class="library-select">
            <option :value="null" disabled>请选择视频集</option>
            <option 
              v-for="lib in libraries" 
              :key="lib.id" 
              :value="lib.id"
            >
              {{ lib.name }}
            </option>
          </select>
        </div>
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

.library-select {
  width: 100%;
  padding: 12px 16px;
  background: #0f0f0f;
  border: 1px solid #333;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: border-color 0.3s ease;
  box-sizing: border-box;
}

.library-select:focus {
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

/* 响应式 */
@media (max-width: 768px) {
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
}
</style>
