// 前端 store 层 mock 测试：验证 store 按域拆分、委托关系正确，且不依赖运行中的后端。
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

// 在导入 store 前 mock axios，使 api 层使用假实例
const mockGet = vi.fn()
const mockPost = vi.fn()
const mockDelete = vi.fn()
vi.mock('axios', () => {
  const instance = {
    get: (...a: any[]) => mockGet(...a),
    post: (...a: any[]) => mockPost(...a),
    delete: (...a: any[]) => mockDelete(...a),
    interceptors: { request: { use: vi.fn() }, response: { use: vi.fn() } },
    defaults: {}
  }
  const axios = { create: () => instance, default: {} }
  return { ...axios, default: axios }
})

import { useTagStore } from '../src/stores/tagStore'
import { useVideoStore } from '../src/stores/videoStore'
import { useGalleryStore } from '../src/stores/galleryStore'
import { useWatchLaterStore } from '../src/stores/watchLaterStore'
import { useUserStore } from '../src/stores/userStore'
import { tagApi, watchLaterApi } from '../src/api'

describe('tagStore 独立拆分', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockGet.mockReset(); mockPost.mockReset(); mockDelete.mockReset()
    mockGet.mockResolvedValue({ success: true, tags: [{ id: 1, name: '测试', video_count: 0 }] })
    mockPost.mockResolvedValue({ success: true })
    mockDelete.mockResolvedValue({ success: true })
  })
  afterEach(() => vi.restoreAllMocks())

  it('fetchTags 调用 tagApi.getTags 并写入 tags', async () => {
    const store = useTagStore()
    const res = await store.fetchTags()
    expect(mockGet).toHaveBeenCalledWith('/api/tags', expect.anything())
    expect(store.tags.length).toBe(1)
    expect(store.tags[0].id).toBe(1)
    expect(res.tags.length).toBe(1)
  })

  it('createTag 成功后自动刷新标签列表（触发 getTags）', async () => {
    const store = useTagStore()
    const getSpy = vi.spyOn(tagApi, 'getTags')
    await store.createTag('新标签', '分类', undefined, [])
    expect(mockPost).toHaveBeenCalledWith('/api/tags', {
      name: '新标签', category: '分类', parent_id: undefined, qualifiers: []
    })
    // 成功后应触发一次 fetchTags（getTags）
    expect(getSpy).toHaveBeenCalled()
  })

  it('deleteTag 成功后从本地列表移除', async () => {
    const store = useTagStore()
    store.tags = [{ id: 1, name: 'a', video_count: 0 }] as any
    await store.deleteTag(1)
    expect(mockDelete).toHaveBeenCalledWith('/api/tags/1')
    expect(store.tags.find((t) => t.id === 1)).toBeUndefined()
  })
})

describe('videoStore 标签委托', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockGet.mockReset(); mockPost.mockReset()
    mockGet.mockResolvedValue({ success: true, tags: [{ id: 2, name: 'v', video_count: 0 }] })
    mockPost.mockResolvedValue({ success: true })
  })
  afterEach(() => vi.restoreAllMocks())

  it('videoStore.tags 引用 tagStore.tags（只读，不重复持有状态）', async () => {
    const vStore = useVideoStore()
    const tStore = useTagStore()
    await tStore.fetchTags()
    expect(vStore.tags).toBe(tStore.tags)
    expect(vStore.tags.length).toBe(1)
  })

  it('videoStore.createTag 委托 tagStore.createTag', async () => {
    const vStore = useVideoStore()
    const spy = vi.spyOn(tagApi, 'createTag').mockResolvedValue({ success: true } as any)
    await vStore.createTag('委托标签')
    expect(spy).toHaveBeenCalledWith('委托标签', undefined, undefined, undefined)
  })

  it('videoStore.searchTags 委托 tagStore.searchTags', async () => {
    const vStore = useVideoStore()
    const spy = vi.spyOn(tagApi, 'searchTags').mockResolvedValue({ success: true, tags: [] } as any)
    const res = await vStore.searchTags('关键词')
    expect(spy).toHaveBeenCalledWith('关键词', undefined)
    expect(res).toEqual([])
  })
})

describe('galleryStore / watchLaterStore / userStore 静态解耦', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockGet.mockReset(); mockPost.mockReset(); mockDelete.mockReset()
    mockGet.mockResolvedValue({ success: true, data: [] })
    mockPost.mockResolvedValue({ success: true })
    mockDelete.mockResolvedValue({ success: true })
  })
  afterEach(() => vi.restoreAllMocks())

  it('galleryStore 使用静态导入的 galleryApi（fetchGallerys）', async () => {
    const store = useGalleryStore()
    await store.fetchGallerys()
    // 证明调用落到静态导入的 api 路径（gallery 列表端点）
    expect(mockGet).toHaveBeenCalledWith('/api/galleries', expect.anything())
  })

  it('watchLaterStore 领域 api 暴露 clear 方法并委托', async () => {
    // 验证 watchLaterApi 暴露 clear 方法（store 委托使用）
    expect(typeof (watchLaterApi as any).clear).toBe('function')
    const store = useWatchLaterStore()
    expect(typeof store.clear).toBe('function')
    // 清空时既更新本地状态又调用后端接口
    store.items = [{ type: 'video', id: 'abc', title: 't', addedAt: new Date().toISOString() }] as any
    await store.clear()
    expect(store.items.length).toBe(0)
    expect(mockDelete).toHaveBeenCalledWith('/api/watch-later')
  })

  it('userStore.fetchManageableLibraries 使用 libraryApi.getLibraries（/api/admin/libraries）', async () => {
    const store = useUserStore()
    // 模拟已登录
    ;(store as any).token = 'fake-token'
    await store.fetchManageableLibraries()
    expect(mockGet).toHaveBeenCalledWith('/api/admin/libraries')
  })
})
