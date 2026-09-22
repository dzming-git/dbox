import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router, { ensureExtensionRoutes } from './router'
import './styles/theme.css'
import App from './App.vue'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)

// 不再 await ensureExtensionRoutes() 后才挂载。
// 理由：路由表里已有通用记录 path='/ext/:extId/:pathMatch(.*)*'（name='ext-standalone'），
// 任意 /ext/<id> 无需动态 addRoute 就能直接匹配；而 ensureExtensionRoutes() 只是一次
// /api/ui-extensions 往返（实测 185→217ms），却挡在 app.use(router) 之前——等于把整条
// 首屏链（面板 HTML → SDK → 首屏数据 → 定位）全都排在它后面。
// 改为后台补注册「带各自标题的精确路由」：只影响后续导航的 title，不影响本次进入独立页。
// 直接刷新非 /ext/ 前缀的插件路由（若有）仍由守卫 step4 的兜底重放覆盖。
ensureExtensionRoutes().catch(() => {})
app.use(router)
app.mount('#app')
