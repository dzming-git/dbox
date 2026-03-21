<script setup lang="ts">
import { ref, onMounted } from 'vue'

// 设置状态
const settings = ref({
  // 播放设置
  autoplay: false,
  defaultQuality: 'auto',
  subtitleLanguage: 'zh',
  // 界面设置
  theme: 'dark',
  language: 'zh-CN',
  // 通知设置
  enableNotifications: true,
  notifyOnNewVideos: true
})

const loading = ref(false)
const saved = ref(false)

// 加载设置
onMounted(() => {
  const stored = localStorage.getItem('userSettings')
  if (stored) {
    settings.value = { ...settings.value, ...JSON.parse(stored) }
  }
})

// 保存设置
const saveSettings = () => {
  loading.value = true
  localStorage.setItem('userSettings', JSON.stringify(settings.value))
  
  // 应用主题
  document.body.className = settings.value.theme === 'dark' ? 'dark-theme' : 'light-theme'
  
  setTimeout(() => {
    loading.value = false
    saved.value = true
    setTimeout(() => {
      saved.value = false
    }, 2000)
  }, 500)
}

// 重置设置
const resetSettings = () => {
  if (confirm('确定要重置所有设置为默认值吗？')) {
    settings.value = {
      autoplay: false,
      defaultQuality: 'auto',
      subtitleLanguage: 'zh',
      theme: 'dark',
      language: 'zh-CN',
      enableNotifications: true,
      notifyOnNewVideos: true
    }
    saveSettings()
  }
}

// 清除所有数据
const clearAllData = () => {
  if (confirm('确定要清除所有本地数据吗？这将删除您的收藏、观看历史等数据。')) {
    localStorage.removeItem('favorites')
    localStorage.removeItem('favoritedVideos')
    localStorage.removeItem('likedVideos')
    localStorage.removeItem('watchHistory')
    localStorage.removeItem('userSettings')
    showToast('所有数据已清除')
  }
}

// 提示消息
const toastMessage = ref('')
const showToastFlag = ref(false)
const showToast = (message: string) => {
  toastMessage.value = message
  showToastFlag.value = true
  setTimeout(() => {
    showToastFlag.value = false
  }, 2000)
}
</script>

<template>
  <div class="settings-page">
    <div class="page-header">
      <h1 class="page-title">设置</h1>
    </div>

    <div class="settings-content">
      <!-- 播放设置 -->
      <section class="settings-section">
        <h2 class="section-title">播放设置</h2>
        
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">自动播放</label>
            <p class="setting-desc">打开视频时自动开始播放</p>
          </div>
          <label class="toggle-switch">
            <input 
              type="checkbox" 
              v-model="settings.autoplay"
              data-testid="autoplay-toggle"
            >
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">默认画质</label>
            <p class="setting-desc">选择视频默认播放画质</p>
          </div>
          <select 
            v-model="settings.defaultQuality"
            class="setting-select"
            data-testid="default-quality-select"
          >
            <option value="auto">自动</option>
            <option value="1080p">1080p</option>
            <option value="720p">720p</option>
            <option value="480p">480p</option>
            <option value="360p">360p</option>
          </select>
        </div>

        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">字幕语言</label>
            <p class="setting-desc">选择默认字幕语言</p>
          </div>
          <select 
            v-model="settings.subtitleLanguage"
            class="setting-select"
            data-testid="subtitle-language-select"
          >
            <option value="zh">中文</option>
            <option value="en">English</option>
            <option value="ja">日本語</option>
            <option value="ko">한국어</option>
          </select>
        </div>
      </section>

      <!-- 界面设置 -->
      <section class="settings-section">
        <h2 class="section-title">界面设置</h2>
        
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">主题</label>
            <p class="setting-desc">选择界面主题颜色</p>
          </div>
          <div class="radio-group">
            <label class="radio-label" data-testid="theme-dark-radio">
              <input 
                type="radio" 
                v-model="settings.theme" 
                value="dark"
              >
              <span class="radio-text">深色</span>
            </label>
            <label class="radio-label">
              <input 
                type="radio" 
                v-model="settings.theme" 
                value="light"
              >
              <span class="radio-text">浅色</span>
            </label>
          </div>
        </div>

        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">界面语言</label>
            <p class="setting-desc">选择界面显示语言</p>
          </div>
          <select 
            v-model="settings.language"
            class="setting-select"
            data-testid="interface-language-select"
          >
            <option value="zh-CN">简体中文</option>
            <option value="zh-TW">繁體中文</option>
            <option value="en-US">English</option>
            <option value="ja-JP">日本語</option>
          </select>
        </div>
      </section>

      <!-- 通知设置 -->
      <section class="settings-section">
        <h2 class="section-title">通知设置</h2>
        
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">启用通知</label>
            <p class="setting-desc">接收应用内通知</p>
          </div>
          <label class="toggle-switch">
            <input 
              type="checkbox" 
              v-model="settings.enableNotifications"
            >
            <span class="toggle-slider"></span>
          </label>
        </div>

        <div class="setting-item" v-if="settings.enableNotifications">
          <div class="setting-info">
            <label class="setting-label">新视频提醒</label>
            <p class="setting-desc">有新视频时通知我</p>
          </div>
          <label class="toggle-switch">
            <input 
              type="checkbox" 
              v-model="settings.notifyOnNewVideos"
            >
            <span class="toggle-slider"></span>
          </label>
        </div>
      </section>

      <!-- 数据管理 -->
      <section class="settings-section">
        <h2 class="section-title">数据管理</h2>
        
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">清除所有数据</label>
            <p class="setting-desc">删除所有本地存储的数据，包括收藏、观看历史等</p>
          </div>
          <button 
            class="danger-btn"
            @click="clearAllData"
            data-testid="clear-all-data-button"
          >
            清除数据
          </button>
        </div>
      </section>

      <!-- 操作按钮 -->
      <div class="actions">
        <button 
          class="reset-btn"
          @click="resetSettings"
          data-testid="reset-settings-button"
        >
          重置为默认
        </button>
        <button 
          class="save-btn"
          @click="saveSettings"
          :disabled="loading"
          data-testid="save-settings-button"
        >
          {{ loading ? '保存中...' : '保存设置' }}
        </button>
      </div>
    </div>

    <!-- 保存成功提示 -->
    <div v-if="saved" class="toast success" data-testid="save-success">
      设置已保存
    </div>

    <!-- Toast 提示 -->
    <div v-if="showToastFlag" class="toast">
      {{ toastMessage }}
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  padding: 24px;
  max-width: 800px;
  margin: 0 auto;
  min-height: 100vh;
  background: #0f0f0f;
  color: #fff;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  font-size: 28px;
  font-weight: 600;
  margin: 0;
  color: #fff;
}

.settings-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-section {
  background: #1a1a1a;
  border-radius: 12px;
  padding: 24px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 20px 0;
  color: #fff;
}

.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0;
  border-bottom: 1px solid #333;
}

.setting-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.setting-info {
  flex: 1;
}

.setting-label {
  display: block;
  font-size: 15px;
  font-weight: 500;
  color: #fff;
  margin-bottom: 4px;
}

.setting-desc {
  margin: 0;
  font-size: 13px;
  color: #999;
}

/* Toggle Switch */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 48px;
  height: 24px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #444;
  transition: .3s;
  border-radius: 24px;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: .3s;
  border-radius: 50%;
}

input:checked + .toggle-slider {
  background-color: #2196F3;
}

input:checked + .toggle-slider:before {
  transform: translateX(24px);
}

/* Select */
.setting-select {
  padding: 8px 16px;
  background: #252525;
  border: 1px solid #444;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  min-width: 120px;
}

.setting-select:focus {
  outline: none;
  border-color: #2196F3;
}

/* Radio Group */
.radio-group {
  display: flex;
  gap: 16px;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 14px;
  color: #ccc;
}

.radio-label input[type="radio"] {
  accent-color: #2196F3;
}

/* Buttons */
.danger-btn {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid #f44336;
  border-radius: 8px;
  color: #f44336;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.danger-btn:hover {
  background: rgba(244, 67, 54, 0.1);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 16px;
}

.reset-btn {
  padding: 12px 24px;
  background: transparent;
  border: 1px solid #444;
  border-radius: 8px;
  color: #999;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.reset-btn:hover {
  background: #333;
  color: #fff;
}

.save-btn {
  padding: 12px 24px;
  background: #2196F3;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.save-btn:hover:not(:disabled) {
  background: #1976D2;
}

.save-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
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

.toast.success {
  background: #4caf50;
}

@keyframes fadeInOut {
  0% { opacity: 0; transform: translateX(-50%) translateY(20px); }
  10% { opacity: 1; transform: translateX(-50%) translateY(0); }
  90% { opacity: 1; transform: translateX(-50%) translateY(0); }
  100% { opacity: 0; transform: translateX(-50%) translateY(-20px); }
}

@media (max-width: 768px) {
  .settings-page {
    padding: 16px;
  }

  .page-title {
    font-size: 22px;
  }

  .setting-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .radio-group {
    flex-direction: column;
    gap: 8px;
  }

  .actions {
    flex-direction: column;
  }

  .reset-btn,
  .save-btn {
    width: 100%;
  }
}
</style>
