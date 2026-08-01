import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import TagBadge from '../src/components/TagBadge.vue'
import type { Tag } from '../src/types'

function makeTag(over: Partial<Tag> = {}): Tag {
  return {
    id: 1,
    name: '测试标签',
    path: '测试标签',
    video_count: 12,
    ...over,
  } as Tag
}

describe('TagBadge.vue', () => {
  it('渲染标签名称', () => {
    const wrapper = mount(TagBadge, {
      props: { tag: makeTag() },
    })
    expect(wrapper.find('.tag-name').text()).toBe('测试标签')
  })

  it('当 video_count > 0 时显示格式化后的计数', () => {
    const wrapper = mount(TagBadge, {
      props: { tag: makeTag({ video_count: 1500 }) },
    })
    expect(wrapper.find('.tag-count').text()).toBe('1.5k')
  })

  it('当 video_count 为 0 时不显示计数', () => {
    const wrapper = mount(TagBadge, {
      props: { tag: makeTag({ video_count: 0 }) },
    })
    expect(wrapper.find('.tag-count').exists()).toBe(false)
  })

  it('根据 level 设置样式类', () => {
    const wrapper = mount(TagBadge, {
      props: { tag: makeTag(), level: 3 },
    })
    expect(wrapper.find('.tag').classes()).toContain('tag-level-3')
  })

  it('active 时添加 active 类', () => {
    const wrapper = mount(TagBadge, {
      props: { tag: makeTag(), active: true },
    })
    expect(wrapper.find('.tag').classes()).toContain('active')
  })

  it('点击时 emit click 并携带 tag', async () => {
    const wrapper = mount(TagBadge, {
      props: { tag: makeTag({ id: 42 }) },
    })
    await wrapper.find('.tag').trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
    expect((wrapper.emitted('click')![0][0] as Tag).id).toBe(42)
  })
})
