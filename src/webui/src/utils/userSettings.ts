// 设置逻辑已统一到 settings.ts（支持 用户/全局/浏览器 三层）。
// 这里仅做兼容导出，videoStore / comicStore 仍 import { getDefaultSort }。
export { getDefaultSort, DEFAULT_SETTINGS } from './settings'
