import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useUserStore } from '../stores/userStore'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'Home',
    component: () => import('../views/Home.vue'),
    meta: { title: '首页', requiresAuth: true }
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
    meta: { title: '标签管理', requiresAuth: true }
  },
  {
    path: '/favorites',
    name: 'Favorites',
    component: () => import('../views/Favorites.vue'),
    meta: { title: '我的收藏', requiresAuth: true }
  },
  {
    path: '/history',
    name: 'History',
    component: () => import('../views/History.vue'),
    meta: { title: '观看历史', requiresAuth: true }
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
    path: '/admin',
    name: 'Admin',
    component: () => import('../views/Admin.vue'),
    meta: { title: '管理后台', requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('../views/NotFound.vue'),
    meta: { title: '页面未找到', public: true }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  }
})

// 路由守卫 - 全局认证拦截
router.beforeEach((to, from, next) => {
  const userStore = useUserStore()
  
  // 设置页面标题
  document.title = `${to.meta.title || 'DPlayer'} - DPlayer 1.0`
  
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
  
  // 3. 检查是否需要管理员权限
  if (to.meta.requiresAdmin && !userStore.isAdmin) {
    next({ name: 'Home' })
    return
  }
  
  next()
})

export default router
