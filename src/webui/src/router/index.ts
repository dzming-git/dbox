import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '../stores/userStore'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue'),
    meta: { title: '首页', requiresAuth: true, keepAlive: true }
  },
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/Login.vue'),
    meta: { title: '登录', public: true }
  },
  {
    path: '/video/:hash',
    name: 'Video',
    component: () => import('../views/Video.vue'),
    meta: { title: '视频详情', requiresAuth: true }
  },
  {
    path: '/shared/:shareCode',
    name: 'SharedWatch',
    component: () => import('../views/Video.vue'),
    meta: { title: '共享观看', requiresAuth: true }
  },
  {
    path: '/tags',
    name: 'Tags',
    component: () => import('../views/Tags.vue'),
    meta: { title: '标签管理', requiresAuth: true, keepAlive: true }
  },
  {
    path: '/galleries',
    name: 'Gallerys',
    component: () => import('../views/Gallerys.vue'),
    meta: { title: '图集', requiresAuth: true, keepAlive: true }
  },
  {
    path: '/gallery/:hash',
    name: 'Gallery',
    component: () => import('../views/GalleryReader.vue'),
    meta: { title: '图集阅读', requiresAuth: true }
  },
  {
    path: '/posts',
    name: 'Posts',
    component: () => import('../views/Posts.vue'),
    meta: { title: '帖子', requiresAuth: true }
  },
  {
    path: '/post/:id',
    name: 'PostDetail',
    component: () => import('../views/PostDetail.vue'),
    meta: { title: '帖子详情', requiresAuth: true }
  },
  {
    path: '/texts',
    name: 'Texts',
    component: () => import('../views/Texts.vue'),
    meta: { title: '文本', requiresAuth: true }
  },
  {
    path: '/text/:id',
    name: 'TextDetail',
    component: () => import('../views/TextDetail.vue'),
    meta: { title: '文本详情', requiresAuth: true }
  },
  {
    path: '/search',
    name: 'Search',
    component: () => import('../views/Search.vue'),
    meta: { title: '搜索', requiresAuth: true, keepAlive: true }
  },
  {
    path: '/favorites',
    name: 'Favorites',
    component: () => import('../views/Favorites.vue'),
    meta: { title: '我的收藏', requiresAuth: true }
  },
  {
    path: '/collections',
    name: 'Collections',
    component: () => import('../views/Collections.vue'),
    meta: { title: '合集', requiresAuth: true }
  },
  {
    path: '/likes',
    name: 'Likes',
    component: () => import('../views/Likes.vue'),
    meta: { title: '我的点赞', requiresAuth: true }
  },
  {
    path: '/disliked',
    name: 'Disliked',
    component: () => import('../views/Disliked.vue'),
    meta: { title: '我不喜欢', requiresAuth: true }
  },
  {
    path: '/history',
    name: 'History',
    component: () => import('../views/History.vue'),
    meta: { title: '观看历史', requiresAuth: true }
  },
  {
    path: '/watch-later',
    name: 'WatchLater',
    component: () => import('../views/WatchLater.vue'),
    meta: { title: '稍后再看', requiresAuth: true }
  },
  {
    path: '/settings',
    name: 'Settings',
    component: () => import('../views/Settings.vue'),
    meta: { title: '设置', requiresAuth: true }
  },
  {
    path: '/upload',
    name: 'Upload',
    component: () => import('../views/Upload.vue'),
    meta: { title: '上传视频', requiresAuth: true }
  },
  {
    path: '/feedback',
    name: 'Feedback',
    component: () => import('../views/Feedback.vue'),
    meta: { title: '反馈中心', requiresAuth: true }
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('../views/Tasks.vue'),
    meta: { title: '任务管理器', requiresAuth: true }
  },
  {
    path: '/guide',
    name: 'Guide',
    component: () => import('../views/Guide.vue'),
    meta: { title: '功能指引', requiresAuth: true }
  },
  {
    path: '/feedback/:id',
    name: 'FeedbackDetail',
    component: () => import('../views/Feedback.vue'),
    meta: { title: '反馈详情', requiresAuth: true }
  },
  {
    path: '/admin',
    name: 'Admin',
    component: () => import('../views/Admin.vue'),
    meta: { title: '管理后台', requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/plugins',
    name: 'Plugins',
    component: () => import('../views/Plugins.vue'),
    meta: { title: '扩展管理', requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/plugins/:id/settings',
    name: 'PluginSettings',
    component: () => import('../views/PluginSettings.vue'),
    meta: { title: '插件设置', requiresAuth: true, requiresAdmin: true }
  },
  {
    // 兜底 404：各插件声明的独立全屏路由（如 AI 助手的 /ai-assistant）在应用启动时
    // 由 registerExtensionRoutes() 动态 addRoute 注入，框架不在此硬编码任何插件路径。
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('../views/NotFound.vue'),
    meta: { title: '页面未找到', public: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) {
      return savedPosition
    }
    return { top: 0 }
  }
})

export { routes }

// 插件独立全屏路由：由各插件在 manifest 的 ui.standalone_route 声明（如 "/ai-assistant"）。
// 框架不硬编码任何插件路径——启动后拉取 ui-extensions，凡声明了 standalone_route 且
// 已启用的插件，都在其路径上挂载 ExtensionStandalone 全屏页（按插件 id 注入）。
// 若某插件目录被删除，这里自然不会注册其路由，实现「删掉即无、框架零入侵」。
export async function registerExtensionRoutes() {
  try {
    const res: any = await (await import('../api/script')).scriptApi.listExtensions()
    if (!res?.success) return
    for (const ext of res.extensions || []) {
      const route = ext?.ui?.standalone_route
      if (!route || typeof route !== 'string') continue
      const name = 'ext-' + ext.id
      // 避免重复注册
      if (router.hasRoute(name)) continue
      router.addRoute({
        path: route,
        name,
        component: () => import('../views/ExtensionStandalone.vue'),
        props: { id: ext.id },
        meta: { title: ext.ui?.title || ext.name || ext.id, requiresAuth: true, requiresAdmin: true }
      })
    }
  } catch (e) {
    // 扩展宿主暂不可用时静默忽略：核心功能不受影响，悬浮面板入口仍由 ExtensionHost 提供
  }
}

// 路由守卫 - 全局认证拦截
router.beforeEach(async (to, from, next) => {
  const userStore = useUserStore()
  
  // 设置页面标题
  document.title = `${to.meta.title || 'DBox'} - DBox`
  
  // 1. 公开页面直接放行（登录页等）
  if (to.meta.public) {
    // 如果已登录且访问登录页，跳转到首页
    if (to.name === 'Login' && userStore.isLoggedIn) {
      const redirect = to.query.redirect as string
      next(redirect || '/')
      return
    }
    next()
    return
  }
  
  // 2. 默认所有页面都需要登录（除非明确标记 public: true）
  if (!userStore.isLoggedIn) {
    // 未登录，重定向到登录页，并记录原目标地址
    next({ 
      name: 'Login', 
      query: { redirect: to.fullPath }
    })
    return
  }
  
  // 3. 检查是否需要管理员权限（全局管理员 或 资源库管理员均可进入）
  if (to.meta.requiresAdmin && !userStore.isAdmin) {
    if (userStore.isLoggedIn) {
      // 资源库管理员：拉取可管理库后再放行；否则导向首页
      if (!userStore.canManageResources) {
        await userStore.fetchManageableLibraries()
      }
      if (userStore.canManageResources) {
        next()
        return
      }
    }
    next({ name: 'Home' })
    return
  }
  
  next()
})

export default router
