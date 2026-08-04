// API 模块统一出口。
// 各领域 API 已拆分到独立文件，本文件仅做聚合 re-export。
// `api` 为通用 axios 封装实例（带 token 注入 / 401 刷新拦截器），供未归入
// 具体领域、需裸调端点的模块使用，统一走命名导入 `import { api } from '../api'`，
// 不再提供默认导出，避免隐式通道。
export { api, API_BASE, axios } from './client'

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
export { historyApi } from './history'
export { interactionApi } from './interaction'
export { trashApi } from './trash'
