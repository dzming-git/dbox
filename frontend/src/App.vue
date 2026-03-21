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
})

const handleLogout = () => {
  userStore.logout()
  router.push('/login')
}
</script>

<template>
  <div class="app-container">
    <!-- 登录页面不显示导航栏 -->
    <nav class="nav" v-if="!isLoginPage">
      <div class="nav-left">
        <RouterLink to="/" class="logo">DPlayer 2.0</RouterLink>
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
        <RouterLink to="/favorites" class="nav-link" v-if="userStore.isLoggedIn">收藏</RouterLink>
        <RouterLink to="/history" class="nav-link" v-if="userStore.isLoggedIn">历史</RouterLink>
        <RouterLink to="/upload" class="nav-link upload-nav" v-if="userStore.isLoggedIn">上传</RouterLink>
      </div>
      <div class="nav-right">
        <RouterLink to="/admin" class="nav-link" v-if="userStore.isAdmin">管理</RouterLink>
        
        <!-- 未登录状态 -->
        <RouterLink v-if="!userStore.isLoggedIn" to="/login" class="nav-link login-link">
          登录
        </RouterLink>
        
        <!-- 已登录状态 -->
        <div v-else class="user-menu">
          <RouterLink to="/settings" class="nav-link" title="设置">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
              <path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61 l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41 h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87 C2.62,9.08,2.66,9.34,2.86,9.49l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58 c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54 c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96 c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6 s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"/>
            </svg>
          </RouterLink>
          <span class="username">{{ userStore.user?.username }}</span>
          <span class="role-badge" :class="{ 'root': userStore.isRoot, 'admin': userStore.isAdmin && !userStore.isRoot }">
            {{ userStore.user?.role_name }}
          </span>
          <button class="logout-btn" @click="handleLogout">退出</button>
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
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #1a1a1a;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  padding: 0 20px;
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

.user-menu {
  display: flex;
  align-items: center;
  gap: 12px;
}

.username {
  color: #fff;
  font-weight: 500;
}

.role-badge {
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
  background: #4caf50;
  color: #fff;
}

.role-badge.admin {
  background: #ff9800;
}

.role-badge.root {
  background: #f44336;
}

.logout-btn {
  background: transparent;
  border: 1px solid #666;
  color: #ccc;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.2s;
}

.logout-btn:hover {
  border-color: #ff5252;
  color: #ff5252;
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
    padding: 0 12px;
    gap: 12px;
  }
  
  .nav-left, .nav-right {
    gap: 8px;
  }
  
  .logo {
    font-size: 16px;
  }
  
  .nav-link {
    padding: 6px 10px;
    font-size: 13px;
  }
  
  .username {
    display: none;
  }
  
  .role-badge {
    font-size: 10px;
    padding: 2px 6px;
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
