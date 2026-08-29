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
    path: '/vault',
    name: 'Vault',
    component: () => import('../views/Vault.vue'),
    meta: { title: '凭证保险库', requiresAuth: true, requiresAdmin: true }
  },
  {
    // /ext 命名空间下的全屏兜底路由：静态预注册，避免刷新时扩展宿主接口尚未返回、
    // 动态路由还没注入就落到 404（动态 addRoute 不会重放已完成的初始导航）。
    // 框架不硬编码任何插件 id——插件 id 直接从路径参数取，因此新增插件无需改框架。
    // 各插件仍由 ensureExtensionRoutes() 动态注册其精确路径（带各自标题），
    // 静态段优先于动态段匹配，故精确路由存在时以它为准，本条仅作竞态兜底。
    path: '/ext/:extId',
    name: 'ext-standalone',
    component: () => import('../views/ExtensionStandalone.vue'),
    props: (route: any) => ({ id: route.params.extId }),
    meta: { title: '扩展', requiresAuth: true, requiresAdmin: true }
  },
  {
    // 兜底 404：各插件声明的独立全屏路由（如 CodeBuddy的 /codebuddy）在应用启动时
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

// 插件独立全屏路由：一律为 /ext/<id>，由后端从插件 id（= 扩展文件夹名）推导，
// manifest 不声明任何 URL——文件夹名的唯一性即保证路由唯一，且插件无法占用
// 根路径与核心路由冲突。启动后拉取 ui-extensions，凡返回了 standalone_route
// 的插件，都在其路径上挂载 ExtensionStandalone 全屏页（按插件 id 注入）。
// 框架不硬编码任何插件路径。
// 若某插件目录被删除，这里自然不会注册其路由，实现「删掉即无、框架零入侵」。
// 可重入：注册成功后置位，避免重复拉取/注册
let extRoutesReady = false
export async function ensureExtensionRoutes() {
  if (extRoutesReady) return
  try {
    const res: any = await (await import('../api/script')).scriptApi.listExtensions()
    if (!res?.success) return
    for (const ext of res.extensions || []) {
      // 路由由后端从插件 id（= 文件夹名）推导为 /ext/<id>，前端直接注册
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
    extRoutesReady = true
  } catch (e) {
    // 扩展宿主暂不可用时静默忽略：核心功能不受影响，悬浮面板入口仍由 ExtensionHost 提供
    console.warn('[router] 首次注册扩展独立路由失败（将在导航守卫中重试）:', e)
  }
}

// 兼容旧名
export const registerExtensionRoutes = ensureExtensionRoutes

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

  // 4. 兜底：目标未匹配到任何路由（将落到 404 catch-all）时，尝试注册扩展独立路由后重放一次。
  // 解决「直接刷新 /xxx-standalone 这类扩展独立页时，因异步注册尚未完成而 404」的框架 bug。
  // （main.ts 已把 ensureExtensionRoutes 移到 app.use(router) 之前，此兜底为双保险）
  const resolved = router.resolve(to.fullPath)
  if (resolved.matched.length === 0 || resolved.name === 'NotFound') {
    await ensureExtensionRoutes()
    const re = router.resolve(to.fullPath)
    if (re.matched.length > 0 && re.name !== 'NotFound') {
      next(re.fullPath)
      return
    }
  }

  next()
})

export default router
