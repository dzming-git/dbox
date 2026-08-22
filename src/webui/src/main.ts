import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router, { registerExtensionRoutes } from './router'
import './styles/theme.css'
import App from './App.vue'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

// 动态注册各插件声明的独立全屏路由（如 AI 助手的 /ai-chat）。
// 必须在 router.isReady() 之前完成，避免首屏导航匹配不到刚注册的路由。
registerExtensionRoutes().finally(() => {
  app.mount('#app')
})
