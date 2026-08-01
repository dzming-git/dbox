// API 模块统一出口。
// 各领域 API 已拆分到独立文件（video.ts / gallery.ts / tag.ts 等），
// 本文件仅做聚合 re-export，保证历史 `import { xxxApi } from '@/api'` 全部可用。
export { default as api, API_BASE } from './client'

export { videoApi } from './video'
export { collectionSetApi } from './collectionSet'
export { tagApi } from './tag'
export { configApi } from './config'
export { thumbnailApi, thumbnailManageApi, healthApi } from './thumbnail'
export { libraryApi, logApi } from './library'
export { galleryApi } from './gallery'
export { systemApi, serviceManageApi } from './system'
export { postApi } from './post'
export { resourceApi } from './resource'
export { textApi } from './text'
export { watchLaterApi } from './watchLater'
