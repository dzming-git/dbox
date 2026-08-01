import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { tagApi } from '../api'
import type { Tag } from '../types'

// 标签领域状态独立拆分，避免 videoStore 负担过重，并供 Tags.vue 直接消费。
export const useTagStore = defineStore('tag', () => {
  const tags = ref<Tag[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  const fetchTags = async (params?: { tree?: boolean; merge?: boolean }) => {
    loading.value = true
    try {
      const response = await tagApi.getTags(params) as any
      tags.value = response.tags || []
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '获取标签失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  const createTag = async (
    name: string,
    category?: string,
    parentId?: number,
    qualifiers?: string[]
  ) => {
    try {
      const response = await tagApi.createTag(name, category, parentId, qualifiers) as any
      if (response.success) {
        await fetchTags()
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '创建标签失败'
      throw e
    }
  }

  const updateTag = async (id: number, data: Partial<Tag>) => {
    try {
      const response = await tagApi.updateTag(id, data) as any
      if (response.success) {
        await fetchTags()
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '更新标签失败'
      throw e
    }
  }

  const deleteTag = async (id: number) => {
    try {
      const response = await tagApi.deleteTag(id) as any
      if (response.success) {
        tags.value = tags.value.filter((t) => t.id !== id)
      }
      return response
    } catch (e) {
      error.value = e instanceof Error ? e.message : '删除标签失败'
      throw e
    }
  }

  const searchTags = async (keyword: string, libraryId?: number) => {
    try {
      const response = await tagApi.searchTags(keyword, libraryId) as any
      return (response && response.tags) || []
    } catch (e) {
      error.value = e instanceof Error ? e.message : '搜索标签失败'
      return []
    }
  }

  return {
    tags,
    loading,
    error,
    fetchTags,
    createTag,
    updateTag,
    deleteTag,
    searchTags
  }
})

// 兼容旧代码的便捷只读引用
export const tagStoreTags = () => computed(() => useTagStore().tags)
