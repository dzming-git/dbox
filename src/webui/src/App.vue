<script setup lang="ts">
import { RouterView, RouterLink, useRouter, useRoute } from 'vue-router'
import { useUserStore } from './stores/userStore'
import { useWatchLaterStore } from './stores/watchLaterStore'
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
import { fetchServerSettings, clearServerSettings, getEffectiveSettings } from './utils/settings'
import { applyThemeById, DEFAULT_THEME_ID } from './utils/theme'
import { routes } from './router'
import { useToast } from './composables/useToast'
import { taskApi } from './api/task'
import ExtensionHost from './components/ExtensionHost.vue'
import PullToRefresh from './components/PullToRefresh.vue'

// 需要缓存（浏览器前进/后退时保持界面与滚动位置）的列表页组件名
const cachedViews = routes
  .filter((r) => (r.meta as any)?.keepAlive)
  .map((r) => r.name as string)

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()
const watchLaterStore = useWatchLaterStore()
const taskActionCount = ref(0)
const { toastMessage, showToastFlag } = useToast()

async function loadTaskCount() {
  if (!userStore.isLoggedIn) {
    taskActionCount.value = 0
    return
  }
  try {
    const res: any = await taskApi.actionCount()
    taskActionCount.value = res.count || 0
  } catch (e) {
    // 红点非关键功能，忽略错误
  }
}

// 判断是否在登录页面
const isLoginPage = computed(() => route.path === '/login')

// 全局搜索：同时搜索视频与图集，跳转到统一搜索页
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

// 应用生效的主题（与 Settings 的 applyTheme 保持一致），让首屏即应用主题
function applyStartupTheme() {
  // 通过主题 id 查询注册表的颜色逻辑再应用
  applyThemeById(getEffectiveSettings().theme || DEFAULT_THEME_ID)
}

onMounted(async () => {
  applyStartupTheme()
  document.addEventListener('click', closeUserDropdown)
  updateNavHeight()
  window.addEventListener('resize', updateNavHeight)
  // 拉取「稍后再看」后端列表（登录账号跨设备一致，未登录则回落到本地缓存）
  watchLaterStore.init()
  // 已登录则拉取后端分层设置（用户层 + 全局层），供默认排序等生效
  if (userStore.isLoggedIn) {
    // 等待后端设置（含主题）返回后再应用，否则首屏会回落到默认值导致「主题不保存」
    await fetchServerSettings()
    applyStartupTheme()
    loadTaskCount()
    setInterval(loadTaskCount, 20000)
  }
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

// 登录态变化：登录后拉取后端设置，登出后清空（回落到浏览器层 + 默认值）
watch(
  () => userStore.isLoggedIn,
  async (logged) => {
    if (logged) {
      // 等待后端设置（含主题）返回后再应用，否则会回落到默认值
      await fetchServerSettings()
      watchLaterStore.init()
      loadTaskCount()
    } else {
      clearServerSettings()
      taskActionCount.value = 0
    }
    // 登录/登出后生效的设置层可能变化，重新应用主题
    applyStartupTheme()
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
</script>

<template>
  <div class="app-container" :style="{ '--nav-height': navHeight + 'px' }">
    <!-- 登录页面不显示导航栏 -->
    <nav class="nav" v-if="!isLoginPage" ref="navEl">
      <div class="nav-left">
        <RouterLink to="/" class="logo">
          <svg class="logo-mark" width="30" height="30" viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
            <!-- B 款：等距立方体盒子 + 内部圆角 D -->
            <polygon points="60,20 96,38 60,56 24,38" fill="var(--accent)"/>
            <polygon points="60,56 96,38 96,76 60,94" fill="var(--accent-active)"/>
            <path fill-rule="evenodd" d="M24 38 L60 56 L60 94 L24 76 Z M30 48 L54 60 C56 67 56 81 54 86 L30 74 Z" fill="var(--accent)"/>
          </svg>
          <span class="logo-text">DBox</span>
        </RouterLink>
        <RouterLink to="/tags" class="nav-link">标签</RouterLink>
        <RouterLink to="/collections" class="nav-link" title="合集">合集</RouterLink>
        <div class="nav-search">
          <input
            v-model="searchText"
            class="nav-search-input"
            type="text"
            placeholder="搜索视频、图集..."
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
          <RouterLink to="/watch-later" class="nav-link nav-icon-link watchlater-nav-link" title="稍后再看">
            <span class="watchlater-ico-wrap">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9V8h2v8zm4 0h-2V8h2v8z"/>
              </svg>
              <span v-if="watchLaterStore.count" class="watchlater-badge">{{ watchLaterStore.count }}</span>
            </span>
            <span>稍后再看</span>
          </RouterLink>
          <RouterLink to="/tasks" class="nav-link nav-icon-link task-nav-link" title="任务管理器">
            <span class="task-ico-wrap">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19 3h-4.18C14.4 1.84 13.3 1 12 1c-1.3 0-2.4.84-2.82 2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-7 0c.55 0 1 .45 1 1s-.45 1-1 1-1-.45-1-1 .45-1 1-1zm-2 14l-4-4 1.41-1.41L10 14.17l6.59-6.59L18 9l-8 8z"/>
              </svg>
              <span v-if="taskActionCount > 0" class="task-badge">{{ taskActionCount > 99 ? '99+' : taskActionCount }}</span>
            </span>
            <span>任务</span>
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
            <RouterLink to="/scripts" class="dropdown-item" v-if="userStore.isAdmin" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19.43 12.98c.04-.32.07-.64.07-.98s-.03-.66-.07-.98l2.11-1.65c.19-.15.24-.42.12-.64l-2-3.46c-.12-.22-.39-.3-.61-.22l-2.49 1c-.52-.4-1.08-.73-1.69-.98l-.38-2.65C14.46 2.18 14.25 2 14 2h-4c-.25 0-.46.18-.49.42l-.38 2.65c-.61.25-1.17.59-1.69.98l-2.49-1c-.23-.09-.49 0-.61.22l-2 3.46c-.13.22-.07.49.12.64l2.11 1.65c-.04.32-.07.65-.07.98s.03.66.07.98l-2.11 1.65c-.19.15-.24.42-.12.64l2 3.46c.12.22.39.3.61.22l2.49-1c.52.4 1.08.73 1.69.98l.38 2.65c.03.24.24.42.49.42h4c.25 0 .46-.18.49-.42l.38-2.65c.61-.25 1.17-.59 1.69-.98l2.49 1c.23.09.49 0 .61-.22l2-3.46c.12-.22.07-.49-.12-.64l-2.11-1.65zM12 15.5c-1.93 0-3.5-1.57-3.5-3.5s1.57-3.5 3.5-3.5 3.5 1.57 3.5 3.5-1.57 3.5-3.5 3.5z"/>
              </svg>
              拓展脚本
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
            <RouterLink to="/guide" class="dropdown-item" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 17h-2v-2h2v2zm2.07-7.75l-.9.92C13.45 12.9 13 13.5 13 15h-2v-.5c0-1.1.45-2.1 1.17-2.83l1.24-1.26c.37-.36.59-.86.59-1.41 0-1.1-.9-2-2-2s-2 .9-2 2H8c0-2.21 1.79-4 4-4s4 1.79 4 4c0 .88-.36 1.68-.93 2.25z"/>
              </svg>
              功能指引
            </RouterLink>
            <RouterLink to="/disliked" class="dropdown-item" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M10 15v4a3 3 0 0 0 3 3l4-9V5H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zM17 2h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"/>
              </svg>
              不喜欢
            </RouterLink>
            <RouterLink to="/feedback" class="dropdown-item" @click="showUserDropdown = false">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20 2H4c-1.1 0-1.99.9-1.99 2L2 22l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-7 12h-2v-2h2v2zm0-4h-2V6h2v4z"/>
              </svg>
              反馈中心
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
        </template>
      </div>
    </nav>
    <main class="main-content" :class="{ 'no-nav': isLoginPage }">
      <PullToRefresh>
        <RouterView v-slot="{ Component }">
          <KeepAlive :include="cachedViews">
            <component :is="Component" />
          </KeepAlive>
        </RouterView>
      </PullToRefresh>
    </main>

    <!-- 全局 Toast 宿主：后台上传完成等通知 -->
    <div v-if="showToastFlag" class="global-toast">{{ toastMessage }}</div>

    <!-- 扩展脚本 UI 注入宿主（仅管理员已启用的脚本可见） -->
    <ExtensionHost v-if="userStore.isAdmin" />
  </div>
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font-sans);
  background: var(--bg-base);
  color: var(--text-primary);
  overflow-x: hidden;
  max-width: 100vw;
  /* 关闭浏览器自带的「下拉刷新 / 橡皮筋」，避免与自定义下拉刷新手势冲突 */
  overscroll-behavior-y: contain;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

.app-container {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  max-width: 100vw;
  /* 用 clip 而非 hidden：同样裁剪横向溢出，但不会创建滚动容器，
     因此不会锁死内部 position: sticky（设置页左侧分组导航吸顶需要）。 */
  overflow-x: clip;
}

.nav {
  height: auto;
  min-height: 60px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  background: var(--nav-bg);
  backdrop-filter: saturate(180%) blur(20px);
  -webkit-backdrop-filter: saturate(180%) blur(20px);
  border-bottom: 1px solid var(--border-subtle);
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 100;
  padding: 8px 24px;
  gap: 8px;
  box-shadow: 0 1px 0 var(--border-subtle);
}

.nav-left, .nav-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.logo {
  display: flex;
  align-items: center;
  gap: 8px;
  text-decoration: none;
  color: var(--text-primary);
}

.logo-mark {
  flex-shrink: 0;
  display: block;
}

.logo-text {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.3px;
  color: var(--text-primary);
}

/* 导航栏搜索框 */
.nav-search {
  display: flex;
  align-items: center;
  background: var(--bg-input);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-pill);
  overflow: hidden;
  transition: border-color var(--transition-fast);
}

.nav-search:focus-within {
  border-color: var(--accent-border);
}

.nav-search-input {
  width: 200px;
  border: none;
  background: transparent;
  color: var(--text-primary);
  padding: 8px 16px;
  font-size: 13px;
  outline: none;
}

.nav-search-input::placeholder {
  color: var(--text-tertiary);
}

.nav-search-btn {
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  cursor: pointer;
  padding: 8px 14px;
  display: flex;
  align-items: center;
  transition: color var(--transition-fast);
}

.nav-search-btn:hover {
  color: var(--text-primary);
}

.nav-link {
  color: var(--text-secondary);
  text-decoration: none;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  font-size: 14px;
  transition: color var(--transition-fast), background var(--transition-fast);
}

.nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-surface-hover);
}

.nav-link.router-link-active {
  color: var(--text-primary);
  background: var(--accent-soft);
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
  color: var(--accent);
}

/* 稍后再看（导航栏按钮，区别于 RouterLink） */
.watchlater-nav-link {
  background: transparent;
  border: none;
  font: inherit;
  cursor: pointer;
  color: var(--text-secondary);
}
.watchlater-nav-link:hover {
  color: var(--text-primary);
  background: var(--bg-surface-hover);
}
.watchlater-ico-wrap {
  position: relative;
  display: inline-flex;
}
.watchlater-badge {
  position: absolute;
  top: -6px;
  right: -8px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--danger);
  color: var(--text-on-accent);
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  font-weight: 600;
}
.task-ico-wrap {
  position: relative;
  display: inline-flex;
}
.task-badge {
  position: absolute;
  top: -6px;
  right: -10px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 999px;
  background: var(--danger);
  color: var(--text-on-accent);
  font-size: 10px;
  line-height: 16px;
  text-align: center;
  font-weight: 600;
  box-shadow: 0 0 6px rgba(255, 90, 106, 0.6);
}

/* 手机端：点赞/收藏/历史/稍后再看/任务等图标直接展示在导航栏，
   不使用下拉抽屉收纳（避免入口被藏起来找不到）。 */

.login-link {
  background: var(--accent);
  color: var(--text-on-accent) !important;
  padding: 8px 22px !important;
  border-radius: var(--radius-pill);
  font-weight: 600;
  transition: background var(--transition-fast);
}

.login-link:hover {
  background: var(--accent-hover) !important;
}

.user-avatar-wrapper {
  position: relative;
}

/* PC 端：头像固定钉在右上角，避免导航换行时掉到第二行中间 */
@media (min-width: 601px) {
  .user-avatar-wrapper {
    position: fixed;
    top: 14px;
    right: 24px;
    z-index: 300;
  }
  /* 为固定头像预留右侧空间，避免 nav-right 内图标与其重叠 */
  .nav-right {
    padding-right: 150px;
  }
}

/* 平板断点 601-900px：窄屏下隐藏导航文字、图标紧凑，避免与固定头像拥挤/重叠。
   重点：头像 right 与 .nav-right padding-right 必须匹配，否则图标会钻到头像下方。 */
@media (min-width: 601px) and (max-width: 900px) {
  .user-avatar-wrapper {
    top: 12px;
    right: 16px;
  }
  .user-avatar {
    width: 34px;
    height: 34px;
  }
  /* 平板隐藏用户名与箭头，让头像 wrapper 收缩到仅头像宽度，避免把导航图标挤出重叠 */
  .user-avatar-wrapper .username,
  .user-avatar-wrapper .dropdown-arrow {
    display: none;
  }
  /* 头像约 34px + right 16px + 间距 6px ≈ 56px 右侧预留，确保图标不钻到头像下方 */
  .nav-right {
    padding-right: 56px;
    gap: 8px;
  }
  .nav-icon-link {
    padding: 4px 7px;
  }
  /* 平板同移动端只显图标、隐藏文字标签 */
  .nav-icon-link > span {
    display: none;
  }
  .watchlater-ico-wrap,
  .task-ico-wrap {
    display: inline-flex !important;
  }
  .nav-left {
    gap: 8px;
  }
  .nav-link {
    padding: 4px 8px;
    font-size: 13px;
  }
  .nav-search {
    width: 160px;
  }
}

.user-avatar-trigger {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--radius-pill);
  transition: background var(--transition-fast);
}

.user-avatar-trigger:hover {
  background: var(--bg-surface-hover);
}

.user-avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--accent-hover) 0%, var(--accent) 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 600;
  font-size: 14px;
  color: var(--text-on-accent);
}

.username {
  color: var(--text-primary);
  font-weight: 500;
  font-size: 14px;
}

.dropdown-arrow {
  color: var(--text-tertiary);
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
  background: var(--bg-elevated);
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  min-width: 184px;
  box-shadow: var(--shadow-lg);
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
  color: var(--text-primary);
  font-size: 14px;
}

.dropdown-divider {
  height: 1px;
  background: var(--border-subtle);
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.dropdown-item:hover {
  background: var(--bg-surface-hover);
  color: var(--text-primary);
}

.dropdown-item.logout {
  color: var(--danger);
}

.dropdown-item.logout:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.role-badge {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: var(--radius-sm);
  background: var(--success);
  color: var(--text-on-accent);
  white-space: nowrap;
}

.role-badge.admin {
  background: var(--warning);
  color: var(--bg-surface-2);
}

.role-badge.root {
  background: var(--danger);
}

.main-content {
  padding-top: var(--nav-height, 60px);
  flex: 1;
  max-width: 100vw;
  /* 注意：不要在此设置 overflow-x: hidden，否则会把 overflow-y 隐式变成 auto，
     导致内部 position: sticky 相对此容器失效（设置页左侧分组导航吸顶会失效）。
     横向溢出已由外层 .app-container 的 overflow-x: hidden 兜底。 */
}

.main-content.no-nav {
  padding-top: 0;
}

/* 全局 Toast（后台上传完成通知等） */
.global-toast {
  position: fixed;
  top: 70px;
  left: 50%;
  transform: translateX(-50%);
  background: var(--bg-elevated);
  color: var(--text-primary);
  padding: 10px 20px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-default);
  font-size: 14px;
  z-index: 9999;
  box-shadow: var(--shadow-lg);
  animation: toastSlideIn 0.3s ease;
  max-width: 90vw;
  text-align: center;
}

@keyframes toastSlideIn {
  from {
    opacity: 0;
    transform: translate(-50%, -10px);
  }
  to {
    opacity: 1;
    transform: translate(-50%, 0);
  }
}

/* 图集沉浸全屏阅读模式：隐藏全局导航，铺满全屏 */
body.reader-immersive {
  overflow: hidden;
}
body.reader-immersive .nav {
  display: none !important;
}
body.reader-immersive .main-content {
  padding-top: 0 !important;
}

/* 进入图集阅读器（非沉浸也生效）：隐藏全局导航，避免其固定定位遮挡阅读器
   自己的顶部工具栏（移动端全局导航会换行变高，navHeight 测量不准会盖住工具栏）。
   阅读器本身已有「返回」和完整工具栏，无需再显示全局导航。 */
body.reader-active .nav {
  display: none !important;
}
body.reader-active .main-content {
  padding-top: 0 !important;
}

/* 拓展脚本全屏独立页（如 AI 助手 /ai-chat）：隐藏全局导航，让扩展界面独享整个视口。
   页面自身提供「返回」入口，无需全局导航。仅由 ExtensionStandalone.vue 在挂载时短暂加在 body 上。 */
body.ext-standalone .nav {
  display: none !important;
}
body.ext-standalone .main-content {
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

  /* 移动端导航只显示图标，避免换行挤占两行遮挡搜索框。
     关键：必须用直接子选择器 > span，否则「更多」抽屉（位于 .mobile-more-wrapper
     这个 .nav-icon-link 内部）里的「我的点赞/收藏/历史」文字会被这条规则
     当成 .nav-icon-link 的后代 span 误隐藏，导致抽屉点开空白。 */
  .nav-icon-link > span {
    display: none;
  }
  /* 稍后再看 / 任务图标包裹是直接子 span，需要保留可见（否则图标也一起消失） */
  .watchlater-ico-wrap,
  .task-ico-wrap {
    display: inline-flex !important;
  }

  .nav-icon-link {
    padding: 8px;
  }

  /* 任务按钮始终保持可见 */
  .task-nav-link {
    display: inline-flex !important;
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

  /* 手机端：头像固定钉在右上角，不受导航换行影响 */
  .user-avatar-wrapper {
    position: fixed;
    top: 10px;
    right: 12px;
    z-index: 300;
  }

  /* 为固定头像预留空间，避免与其他导航图标重叠 */
  .nav-right {
    padding-right: 48px;
  }

}


</style>
