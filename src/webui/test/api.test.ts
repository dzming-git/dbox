// 前端 API 层 mock 测试（不依赖运行中的后端服务）。
// 验证拆分后各领域 Api 对象与关键方法存在，并通过 mock axios 验证请求构造正确。
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// 在导入 api 模块前 mock axios，使 client.ts 使用假实例
const mockGet = vi.fn()
const mockPost = vi.fn()
const mockPut = vi.fn()
const mockDelete = vi.fn()
vi.mock('axios', () => {
  const instance = {
    get: (...a: any[]) => mockGet(...a),
    post: (...a: any[]) => mockPost(...a),
    put: (...a: any[]) => mockPut(...a),
    delete: (...a: any[]) => mockDelete(...a),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: {}
  }
  const axios = { create: () => instance, default: {} }
  // 默认导入与具名导入都指向同一个带 create 的对象
  return { ...axios, default: axios }
})

import {
  videoApi, galleryApi, tagApi, libraryApi, configApi,
  systemApi, postApi, resourceApi, textApi, watchLaterApi,
  thumbnailApi, thumbnailManageApi, healthApi, serviceManageApi,
  collectionSetApi, logApi
} from '../src/api'

describe('api 模块完整性', () => {
  it('所有领域 Api 均导出且为对象', () => {
    const apis = { videoApi, galleryApi, tagApi, libraryApi, configApi,
      systemApi, postApi, resourceApi, textApi, watchLaterApi,
      thumbnailApi, thumbnailManageApi, healthApi, serviceManageApi,
      collectionSetApi, logApi }
    for (const [name, api] of Object.entries(apis)) {
      expect(api, name).toBeTypeOf('object')
    }
  })

  it('galleryApi 保留完整方法（含 interact/saveProgress/scanStatus/playlist）', () => {
    const methods = ['getGallerys', 'getGallery', 'interact', 'saveProgress',
      'getFavorites', 'getLikes', 'getDisliked', 'getHistory', 'scan', 'scanStatus',
      'getGalleryTags', 'updateGallery', 'setGalleryTags', 'getPlaylists',
      'createPlaylist', 'deletePlaylist', 'addToPlaylist', 'reorderPlaylist']
    for (const m of methods) {
      expect((galleryApi as any)[m], `galleryApi.${m}`).toBeTypeOf('function')
    }
  })
})

describe('请求构造（mock axios）', () => {
  beforeEach(() => {
    mockGet.mockReset(); mockPost.mockReset(); mockPut.mockReset(); mockDelete.mockReset()
    mockGet.mockResolvedValue({ success: true, data: {} })
    mockPost.mockResolvedValue({ success: true, data: {} })
    mockPut.mockResolvedValue({ success: true, data: {} })
    mockDelete.mockResolvedValue({ success: true, data: {} })
  })

  it('videoApi.getVideos 拼装正确 url 与参数', async () => {
    await videoApi.getVideos({ limit: 10, tag_id: 3, search: '猫' })
    expect(mockGet).toHaveBeenCalledWith('/api/videos', { params: { limit: 10, tag_id: 3, search: '猫' } })
  })

  it('videoApi.likeVideo 使用正确端点', async () => {
    await videoApi.likeVideo('abc123')
    expect(mockPost).toHaveBeenCalledWith('/api/video/abc123/like')
  })

  it('watchLaterApi 走领域 api 而非裸拼', async () => {
    await watchLaterApi.add({ type: 'video', id: 'h1', title: 't' })
    expect(mockPost).toHaveBeenCalledWith('/api/watch-later', { type: 'video', id: 'h1', title: 't' })
    await watchLaterApi.remove('video', 'h1')
    expect(mockDelete).toHaveBeenCalledWith('/api/watch-later/video/h1')
  })

  it('libraryApi.getLibraries 对齐 /api/admin/libraries', async () => {
    await libraryApi.getLibraries()
    expect(mockGet).toHaveBeenCalledWith('/api/admin/libraries')
  })

  it('videoApi.getLibraries 对齐 /api/user/libraries', async () => {
    await videoApi.getLibraries()
    expect(mockGet).toHaveBeenCalledWith('/api/user/libraries')
  })

  it('postApi.create 通过 data.refs 携带资源引用', async () => {
    await postApi.create({ title: 't', content: 'c', refs: [{ resource_index_id: 5, note: 'x' }] })
    expect(mockPost).toHaveBeenCalledWith('/api/posts', { title: 't', content: 'c', refs: [{ resource_index_id: 5, note: 'x' }] })
  })
})

afterEach(() => {
  vi.clearAllMocks()
})
