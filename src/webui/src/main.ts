import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router, { ensureExtensionRoutes } from './router'
import './styles/theme.css'
import App from './App.vue'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)

// 关键修复：必须在 app.use(router) 之前完成扩展独立路由注册。
// Vue Router 在 app.use(router) 时会触发初始导航（基于当时的 matcher 快照）；
// 若此时扩展路由尚未 addRoute，刷新 /xxx-standalone 会匹配到 404 catch-all，
// 且后续 addRoute 不会重放已完成/进行中的初始导航（框架 bug）。
// 因此把 ensureExtensionRoutes() 的 await 放在 app.use(router) 之前，
// 路由守卫 also 提供兜底重放（ensureExtensionRoutes），双保险根除竞态。
;(async () => {
  await ensureExtensionRoutes()
  app.use(router)
  app.mount('#app')
})()
