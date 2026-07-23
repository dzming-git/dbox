<script setup lang="ts">
import { RouterView, RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from './stores/userStore'
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { submitSuggestion } from './api/suggestion'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// 判断是否在登录页面
const isLoginPage = computed(() => route.path === '/login')

// 全局搜索：同时搜索视频与漫画，跳转到统一搜索页
const searchText = ref('')
const handleNavSearch = () => {
  const q = searchText.value.trim()
  router.push({ path: '/search', query: q ? { q } : {} })
}

// 用户下拉菜单状态
const showUserDropdown = ref(false)

// 导航栏实际高度，用于动态设置内容区顶部内边距（避免导航换行后遮挡搜索框）
const navEl = ref<HTMLElement | null>(null)
const navHeight = ref(60)
const updateNavHeight = () => {
  navHeight.value = navEl.value ? navEl.value.offsetHeight : 0
}

// 建议对话框状态
const showSuggestionDialog = ref(false)
const suggestionContent = ref('')
const suggestionContact = ref('')
const suggestionSubmitting = ref(false)
const suggestionMessage = ref('')
const suggestionSuccess = ref(false)

onMounted(() => {
  document.addEventListener('click', closeUserDropdown)
  updateNavHeight()
  window.addEventListener('resize', updateNavHeight)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateNavHeight)
})

// 登录/登出、路由切换后导航栏结构会变化，重新测量高度
watch(
  () => [route.path, userStore.isLoggedIn],
  async () => {
    await nextTick()
    updateNavHeight()
  }
)

const handleLogout = () => {
  userStore.logout()
  router.push('/login')
  showUserDropdown.value = false
}

// 点击外部关闭下拉菜单
const closeUserDropdown = (event: MouseEvent) => {
  const target = event.target as HTMLElement
  if (!target.closest('.user-avatar-wrapper')) {
    showUserDropdown.value = false
  }
}

// 打开建议对话框
const openSuggestionDialog = () => {
  showUserDropdown.value = false
  showSuggestionDialog.value = true
  suggestionContent.value = ''
  suggestionContact.value = ''
  suggestionMessage.value = ''
  suggestionSuccess.value = false
}

// 关闭建议对话框
const closeSuggestionDialog = () => {
  showSuggestionDialog.value = false
}

// 提交建议
const handleSubmitSuggestion = async () => {
  if (!suggestionContent.value.trim()) {
    suggestionMessage.value = '请输入建议内容'
    return
  }

  if (suggestionContent.value.trim().length < 5) {
    suggestionMessage.value = '建议内容太短，请详细描述'
    return
  }

  suggestionSubmitting.value = true
  suggestionMessage.value = ''

  try {
    const result = await submitSuggestion(
      suggestionContent.value.trim(),
      suggestionContact.value.trim() || undefined
    )

    if (result.success) {
      suggestionSuccess.value = true
      suggestionMessage.value = result.message || '感谢您的建议！'
      setTimeout(() => {
        closeSuggestionDialog()
      }, 1500)
    } else {
      suggestionMessage.value = result.error || '提交失败，请重试'
    }
  } catch (e) {
    suggestionMessage.value = '网络错误，请重试'
  } finally {
    suggestionSubmitting.value = false
  }
}
</script>

<template>
  <div class="app-container" :style="{ '--nav-height': navHeight + 'px' }">
    <!-- 登录页面不显示导航栏 -->
    <nav class="nav" v-if="!isLoginPage" ref="navEl">
      <div class="nav-left">
        <RouterLink to="/" class="logo">DPlayer</RouterLink>
        <RouterLink to="/tags" class="nav-link">标签</RouterLink>
        <RouterLink to="/collections" class="nav-link" title="合集">合集</RouterLink>
        <div class="nav-search">
          <input
            v-model="searchText"
            class="nav-search-input"
            type="text"
            placeholder="搜索视频、漫画..."
            @keyup.enter="handleNavSearch"
          />
          <button class="nav-search-btn" @click="handleNavSearch" title="搜索">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="11" cy="11" r="8"/>
              <path d="M21 21l-4.35-4.35"/>
            </svg>
          </button>
        </div>
      </div>
      <div class="nav-right">
        <!-- 未登录状态 -->
        <RouterLink v-if="!userStore.isLoggedIn" to="/login" class="nav-link login-link">
          登录
        </RouterLink>
        
        <!-- 已登录状态 -->
        <template v-else>
          <!-- 常用功能直接放在导航栏，避免下拉菜单不便 -->
          <RouterLink to="/likes" class="nav-link nav-icon-link" title="点赞">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/>
            </svg>
            <span>点赞</span>
          </RouterLink>
          <RouterLink to="/favorites" class="nav-link nav-icon-link" title="收藏">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
            </svg>
            <span>收藏</span>
          </RouterLink>
          <RouterLink to="/history" class="nav-link nav-icon-link" title="历史">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
              <path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/>
            </svg>
            <span>历史</span>
          </RouterLink>

          <!-- 用户头像下拉菜单 -->
          <div class="user-avatar-wrapper">
            <div class="user-avatar-trigger" @click.stop="showUserDropdown = !showUserDropdown">
            <div class="user-avatar">
              {{ userStore.user?.username?.charAt(0)?.toUpperCase() || 'U' }}
            </div>
            <span class="username">{{ userStore.user?.username }}</span>
            <svg class="dropdown-arrow" :class="{ 'up': showUserDropdown }" width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <path d="M7 10l5 5 5-5z"/>
            </svg>
          </div>
          
          <!-- 用户下拉菜单 -->
          <div class="user-dropdown" v-if="showUserDropdown">
            <div class="dropdown-header">
              <span class="dropdown-username">{{ userStore.user?.username }}</span>
              <span class="role-badge" :class="{ 'root': userStore.isRoot, 'admin': userStore.isAdmin && !userStore.isRoot }">
                {{ userStore.user?.role_name }}
              </span>
            </div>
            <div class="dropdown-divider"></div>
            <RouterLink to="/admin" class="dropdown-item" v-if="userStore.isAdmin" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/>
              </svg>
              管理
            </RouterLink>
            <RouterLink to="/upload" class="dropdown-item" v-if="userStore.isAdmin" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M9 16h6v-6h4l-7-7-7 7h4v6zm-4 2h14v2H5v-2z"/>
              </svg>
              上传视频
            </RouterLink>
            <RouterLink to="/settings" class="dropdown-item" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61 l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41 h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87 C2.62,9.08,2.66,9.34,2.86,9.49l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58 c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54 c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96 c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6 s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"/>
              </svg>
              设置
            </RouterLink>
            <RouterLink to="/disliked" class="dropdown-item" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
              </svg>
              不喜欢
            </RouterLink>
            <div class="dropdown-item" @click="openSuggestionDialog">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-7 12h-2v-2h2v2zm0-4h-2V6h2v4z"/>
              </svg>
              意见建议
            </div>
            <div class="dropdown-divider"></div>
            <div class="dropdown-item logout" @click="handleLogout">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/>
              </svg>
              退出登录
            </div>
          </div>
          </div>
        </template>
      </div>
    </nav>
    <main class="main-content" :class="{ 'no-nav': isLoginPage }">
      <RouterView />
    </main>

    <!-- 意见建议对话框 -->
    <div v-if="showSuggestionDialog" class="dialog-overlay" @click.self="closeSuggestionDialog">
      <div class="dialog suggestion-dialog">
        <div class="dialog-header">
          <h3>意见建议</h3>
          <button class="close-btn" @click="closeSuggestionDialog">&times;</button>
        </div>
        <div class="dialog-body">
          <p class="suggestion-desc">如果您有任何功能建议、Bug反馈或改进意见，欢迎告诉我们！</p>
          <div class="form-group">
            <label>建议内容 <span class="required">*</span></label>
            <textarea
              v-model="suggestionContent"
              class="suggestion-textarea"
              placeholder="请详细描述您的建议..."
              rows="6"
              :disabled="suggestionSubmitting"
            ></textarea>
            <div class="char-count">{{ suggestionContent.length }}/2000</div>
          </div>
          <div class="form-group">
            <label>联系方式（选填）</label>
            <input
              v-model="suggestionContact"
              type="text"
              class="suggestion-input"
              placeholder="邮箱或联系方式，方便我们回复您"
              :disabled="suggestionSubmitting"
            />
          </div>
          <div v-if="suggestionMessage" class="suggestion-message" :class="{ success: suggestionSuccess }">
            {{ suggestionMessage }}
          </div>
        </div>
        <div class="dialog-footer">
          <button class="btn-secondary" @click="closeSuggestionDialog" :disabled="suggestionSubmitting">
            取消
          </button>
          <button class="btn-primary" @click="handleSubmitSuggestion" :disabled="suggestionSubmitting">
            {{ suggestionSubmitting ? '提交中...' : '提交建议' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #121212;
  color: #fff;
  overflow-x: hidden;
  max-width: 100vw;
}

.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  max-width: 100vw;
  overflow-x: hidden;
}

.nav {
  height: auto;
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  background: #1a1a1a;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  padding: 8px 20px;
  gap: 8px;
}

.nav-left, .nav-right {
  display: flex;
  align-items: center;
  gap: 24px;
}

.logo {
  font-size: 20px;
  font-weight: bold;
  color: #fff;
  text-decoration: none;
}

/* 导航栏搜索框 */
.nav-search {
  display: flex;
  align-items: center;
  background: #2a2a2a;
  border: 1px solid #333;
  border-radius: 8px;
  overflow: hidden;
}

.nav-search-input {
  width: 200px;
  border: none;
  background: transparent;
  color: #fff;
  padding: 8px 12px;
  font-size: 13px;
  outline: none;
}

.nav-search-input::placeholder {
  color: #777;
}

.nav-search-btn {
  background: transparent;
  border: none;
  color: #aaa;
  cursor: pointer;
  padding: 8px 10px;
  display: flex;
  align-items: center;
}

.nav-search-btn:hover {
  color: #fff;
}

.nav-link {
  color: #ccc;
  text-decoration: none;
  padding: 8px 16px;
  border-radius: 4px;
  transition: color 0.2s, background 0.2s;
}

.nav-link:hover {
  color: #fff;
  background: rgba(255, 255, 255, 0.1);
}

.nav-link.router-link-active {
  color: #2196F3;
}

/* 导航栏图标+文字链接（收藏/历史） */
.nav-icon-link {
  display: flex;
  align-items: center;
  gap: 6px;
}

.nav-icon-link svg {
  flex-shrink: 0;
}

.nav-icon-link.router-link-active svg {
  color: #2196F3;
}

.login-link {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: #fff !important;
  padding: 8px 20px !important;
  border-radius: 6px;
  font-weight: 500;
}

.login-link:hover {
  opacity: 0.9;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
}

.user-avatar-wrapper {
  position: relative;
}

.user-avatar-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 8px;
  transition: background 0.2s;
}

.user-avatar-trigger:hover {
  background: rgba(255, 255, 255, 0.1);
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
  color: #fff;
}

.username {
  color: #fff;
  font-weight: 500;
  font-size: 14px;
}

.dropdown-arrow {
  color: #888;
  transition: transform 0.2s;
}

.dropdown-arrow.up {
  transform: rotate(180deg);
}

.user-dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 8px;
  background: #2a2a2a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 12px;
  min-width: 180px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  overflow: hidden;
  z-index: 200;
  animation: dropdownFadeIn 0.2s ease;
}

@keyframes dropdownFadeIn {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.dropdown-header {
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.dropdown-username {
  font-weight: 600;
  color: #fff;
  font-size: 14px;
}

.dropdown-divider {
  height: 1px;
  background: rgba(255, 255, 255, 0.1);
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  color: #ccc;
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.dropdown-item:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #fff;
}

.dropdown-item.logout {
  color: #ff6b6b;
}

.dropdown-item.logout:hover {
  background: rgba(255, 107, 107, 0.1);
  color: #ff6b6b;
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
  z-index: 10000;
}

.dialog {
  background: #2a2a2a;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.5);
  max-height: 90vh;
  overflow-y: auto;
}

.dialog-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.dialog-header h3 {
  font-size: 18px;
  font-weight: 600;
  color: #fff;
}

.close-btn {
  background: none;
  border: none;
  color: #888;
  font-size: 24px;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.close-btn:hover {
  color: #fff;
}

.role-badge {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 4px;
  background: #4caf50;
  color: #fff;
  white-space: nowrap;
}

.role-badge.admin {
  background: #ff9800;
}

.role-badge.root {
  background: #f44336;
}

.main-content {
  padding-top: var(--nav-height, 60px);
  flex: 1;
  max-width: 100vw;
  overflow-x: hidden;
}

.main-content.no-nav {
  padding-top: 0;
}

/* 漫画沉浸全屏阅读模式：隐藏全局导航，铺满全屏 */
body.reader-immersive {
  overflow: hidden;
}
body.reader-immersive .nav {
  display: none !important;
}
body.reader-immersive .main-content {
  padding-top: 0 !important;
}

/* 进入漫画阅读器（非沉浸也生效）：隐藏全局导航，避免其固定定位遮挡阅读器
   自己的顶部工具栏（移动端全局导航会换行变高，navHeight 测量不准会盖住工具栏）。
   阅读器本身已有「返回」和完整工具栏，无需再显示全局导航。 */
body.reader-active .nav {
  display: none !important;
}
body.reader-active .main-content {
  padding-top: 0 !important;
}

/* 响应式导航 */
@media (max-width: 600px) {
  .nav {
    padding: 8px 10px;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  
  .nav-left {
    flex: 1 1 auto;
    min-width: 0;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  
  .nav-right {
    flex: 0 0 auto;
    gap: 2px;
    flex-wrap: nowrap;
    justify-content: flex-end;
    align-self: flex-start;
  }
  
  /* 移动端搜索框独占整行，避免与图标挤在一起溢出 */
  .nav-search {
    flex: 1 1 100%;
    order: 5;
    margin-top: 4px;
  }
  
  .nav-search-input {
    width: 100%;
  }
  
  /* 移动端导航只显示图标，避免换行挤占两行遮挡搜索框 */
  .nav-icon-link span {
    display: none;
  }
  
  .nav-icon-link {
    padding: 8px;
  }
  
  .logo {
    font-size: 18px;
  }
  
  .nav-link {
    padding: 6px 8px;
    font-size: 13px;
    white-space: nowrap;
  }
  
  .user-avatar-trigger {
    padding: 2px;
  }
  
  .username {
    display: none;
  }
  
  .user-avatar {
    width: 28px;
    height: 28px;
    font-size: 12px;
  }
  
  .dropdown-arrow {
    display: none;
  }

  .user-dropdown {
    min-width: 160px;
    right: -8px;
  }

  .dropdown-item {
    padding: 8px 12px;
    font-size: 13px;
  }
}

/* 建议对话框样式 */
.suggestion-dialog {
  width: 500px;
  max-width: 90vw;
}

.suggestion-dialog .dialog-body {
  padding: 20px 0;
}

.suggestion-desc {
  color: #888;
  font-size: 14px;
  margin-bottom: 20px;
  line-height: 1.6;
}

.suggestion-textarea {
  width: 100%;
  padding: 12px;
  background: #1a1a1a;
  border: 1px solid #444;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  resize: vertical;
  min-height: 120px;
  font-family: inherit;
}

.suggestion-textarea:focus {
  outline: none;
  border-color: #2196F3;
}

.suggestion-textarea:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.suggestion-input {
  width: 100%;
  padding: 10px 12px;
  background: #1a1a1a;
  border: 1px solid #444;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
}

.suggestion-input:focus {
  outline: none;
  border-color: #2196F3;
}

.suggestion-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.char-count {
  text-align: right;
  font-size: 12px;
  color: #666;
  margin-top: 4px;
}

.suggestion-message {
  padding: 10px 12px;
  border-radius: 6px;
  font-size: 14px;
  margin-top: 12px;
  background: rgba(255, 107, 107, 0.15);
  color: #ff6b6b;
  border: 1px solid rgba(255, 107, 107, 0.3);
}

.suggestion-message.success {
  background: rgba(76, 175, 80, 0.15);
  color: #4caf50;
  border-color: rgba(76, 175, 80, 0.3);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 16px;
  border-top: 1px solid #333;
}

.btn-secondary {
  padding: 10px 20px;
  background: #333;
  border: 1px solid #444;
  border-radius: 6px;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-secondary:hover:not(:disabled) {
  background: #444;
}

.btn-secondary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
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

.btn-primary:hover:not(:disabled) {
  background: #1976D2;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
