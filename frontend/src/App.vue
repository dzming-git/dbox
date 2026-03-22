<script setup lang="ts">
import { RouterView, RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from './stores/userStore'
import { ref, onMounted, computed } from 'vue'
import { libraryApi } from './api'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

// 判断是否在登录页面
const isLoginPage = computed(() => route.path === '/login')

// 用户下拉菜单状态
const showUserDropdown = ref(false)

// 视频库切换器状态
const userLibraries = ref<any[]>([])
const currentLibraryId = ref<number | null>(null)
const showLibrarySwitcher = ref(false)

// 获取用户可访问的视频库
const fetchUserLibraries = async () => {
  try {
    const res = await libraryApi.getUserLibraries() as any
    if (res.success) {
      userLibraries.value = res.data || []
      currentLibraryId.value = res.current_library
    }
  } catch (error) {
    console.error('获取视频库列表失败:', error)
  }
}

// 切换视频库
const switchLibrary = async (libraryId: number) => {
  try {
    const res = await libraryApi.switchLibrary(libraryId) as any
    if (res.success) {
      currentLibraryId.value = libraryId
      showLibrarySwitcher.value = false
      // 刷新页面以加载新数据
      window.location.reload()
    }
  } catch (error) {
    console.error('切换视频库失败:', error)
  }
}

// 获取当前视频库名称
const currentLibraryName = computed(() => {
  const lib = userLibraries.value.find(l => l.id === currentLibraryId.value)
  return lib?.name || '默认'
})

onMounted(() => {
  if (userStore.isLoggedIn) {
    fetchUserLibraries()
  }
  document.addEventListener('click', closeUserDropdown)
})

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
</script>

<template>
  <div class="app-container">
    <!-- 登录页面不显示导航栏 -->
    <nav class="nav" v-if="!isLoginPage">
      <div class="nav-left">
        <RouterLink to="/" class="logo">DPlayer</RouterLink>
        <!-- 视频库切换器 -->
        <div class="library-switcher" v-if="userStore.isLoggedIn && userLibraries.length > 1">
          <button class="switcher-btn" @click="showLibrarySwitcher = !showLibrarySwitcher">
            📁 {{ currentLibraryName }}
          </button>
          <div class="switcher-dropdown" v-if="showLibrarySwitcher">
            <div
              v-for="lib in userLibraries"
              :key="lib.id"
              class="switcher-option"
              :class="{ active: lib.id === currentLibraryId }"
              @click="switchLibrary(lib.id)"
            >
              {{ lib.name }}
              <span class="access-level">{{ lib.access_level === 'full' ? '完全访问' : lib.access_level === 'write' ? '可读写' : '只读' }}</span>
            </div>
          </div>
        </div>
        <RouterLink to="/tags" class="nav-link">标签</RouterLink>
        <RouterLink to="/upload" class="nav-link upload-nav" v-if="userStore.isLoggedIn">上传</RouterLink>
      </div>
      <div class="nav-right">
        <!-- 未登录状态 -->
        <RouterLink v-if="!userStore.isLoggedIn" to="/login" class="nav-link login-link">
          登录
        </RouterLink>
        
        <!-- 已登录状态 - 用户头像下拉菜单 -->
        <div v-else class="user-avatar-wrapper">
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
            <RouterLink to="/favorites" class="dropdown-item" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/>
              </svg>
              收藏
            </RouterLink>
            <RouterLink to="/history" class="dropdown-item" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M13 3c-4.97 0-9 4.03-9 9H1l3.89 3.89.07.14L9 12H6c0-3.87 3.13-7 7-7s7 3.13 7 7-3.13 7-7 7c-1.93 0-3.68-.79-4.94-2.06l-1.42 1.42C8.27 19.99 10.51 21 13 21c4.97 0 9-4.03 9-9s-4.03-9-9-9zm-1 5v5l4.28 2.54.72-1.21-3.5-2.08V8H12z"/>
              </svg>
              历史
            </RouterLink>
            <RouterLink to="/settings" class="dropdown-item" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61 l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41 h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87 C2.62,9.08,2.66,9.34,2.86,9.49l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58 c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54 c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96 c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6 s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"/>
              </svg>
              设置
            </RouterLink>
            <div class="dropdown-divider"></div>
            <div class="dropdown-item logout" @click="handleLogout">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M17 7l-1.41 1.41L18.17 11H8v2h10.17l-2.58 2.58L17 17l5-5zM4 5h8V3H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h8v-2H4V5z"/>
              </svg>
              退出登录
            </div>
          </div>
        </div>
      </div>
    </nav>
    <main class="main-content" :class="{ 'no-nav': isLoginPage }">
      <RouterView />
    </main>
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
  padding-top: 60px;
  flex: 1;
  max-width: 100vw;
  overflow-x: hidden;
}

.main-content.no-nav {
  padding-top: 0;
}

/* 响应式导航 */
@media (max-width: 600px) {
  .nav {
    padding: 8px 12px;
    gap: 8px;
  }
  
  .nav-left {
    gap: 4px;
    flex-wrap: wrap;
  }
  
  .nav-right {
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  
  .logo {
    font-size: 16px;
  }
  
  .nav-link {
    padding: 6px 10px;
    font-size: 13px;
    white-space: nowrap;
  }
  
  .user-avatar-trigger {
    padding: 4px;
  }
  
  .username {
    display: inline;
    font-size: 12px;
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

/* 视频库切换器样式 */
.library-switcher {
  position: relative;
}

.switcher-btn {
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  color: #fff;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: all 0.2s;
}

.switcher-btn:hover {
  background: rgba(255, 255, 255, 0.2);
}

.switcher-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  margin-top: 4px;
  background: #2a2a2a;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  min-width: 180px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
  overflow: hidden;
  z-index: 200;
}

.switcher-option {
  padding: 10px 14px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background 0.2s;
  font-size: 14px;
}

.switcher-option:hover {
  background: rgba(255, 255, 255, 0.1);
}

.switcher-option.active {
  background: rgba(102, 126, 234, 0.3);
  color: #a0a0ff;
}

.access-level {
  font-size: 11px;
  color: #888;
  padding: 2px 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 4px;
}
</style>
