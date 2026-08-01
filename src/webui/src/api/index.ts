// API 模块统一出口。
// 各领域 API 已拆分到独立文件，本文件仅做聚合 re-export，保证历史导入兼容。
// 同时保留默认导出 axios 实例（供需要裸调用的模块 `import api from '@/api'` 使用）。
import apiClient from './client'

export default apiClient
export { API_BASE, axios } from './client'

export { videoApi } from './video'
export { collectionSetApi } from './collectionSet'
export { tagApi } from './tag'
export { configApi } from './config'
export { thumbnailApi } from './thumbnail'
export { healthApi } from './thumbnail'
export { libraryApi } from './library'
export { logApi } from './library'
export { thumbnailManageApi } from './thumbnail'
export { serviceManageApi } from './system'
export { galleryApi } from './gallery'
export { systemApi } from './system'
export { postApi } from './post'
export { resourceApi } from './resource'
export { textApi } from './text'
export { watchLaterApi } from './watchLater'
