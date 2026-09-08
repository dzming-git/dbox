import router from '../router'
import { useUserStore } from '../stores/userStore'

/**
 * 入口可见性判定：**唯一判据是路由 meta**。
 *
 * 背景：此前「菜单可见性」与「路由权限」是两套判据——菜单各写各的 v-if
 * （典型如 /upload：路由只 requiresAuth、菜单却按 isAdmin 藏；而后端上传接口
 * 本就是 @auth_required），时间一长必然漂移，表现为「路由进得去但菜单看不见」
 * 或「菜单看得见但进去被弹回」。
 *
 * 这里把规则收敛成与 router/index.ts 全局守卫完全一致的单一实现，
 * 导航栏、头像菜单、应用列表等所有入口都只问这一个函数，
 * 新增页面只需在路由 meta 上声明一次权限，无需再到处补 v-if。
 */
export function canShow(path: string): boolean {
  const userStore = useUserStore()
  const meta = (router.resolve(path).meta || {}) as {
    public?: boolean
    requiresAuth?: boolean
    requiresAdmin?: boolean
  }
  // 与守卫第 1 步一致：公开页面永远可见
  if (meta.public) return true
  // 与守卫第 2 步一致：默认需要登录
  if (!userStore.isLoggedIn) return false
  // 与守卫第 3 步一致：需要管理权限时，全局管理员或资源库管理员均可
  if (meta.requiresAdmin) return !!userStore.isAdmin || !!userStore.canManageResources
  return true
}
