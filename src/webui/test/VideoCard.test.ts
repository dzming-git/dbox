import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import VideoCard from '../src/components/VideoCard.vue'
import { useUserStore } from '../src/stores/userStore'
import type { Video } from '../src/types'

function makeVideo(over: Partial<Video> = {}): Video {
  return {
    hash: 'abc123',
    title: '示例视频',
    thumbnail: '',
    duration: 125,
    view_count: 100,
    like_count: 0,
    is_liked: false,
    tags: [],
    ...over,
  } as Video
}

describe('VideoCard.vue', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('渲染标题与播放次数', () => {
    const wrapper = mount(VideoCard, {
      props: { video: makeVideo({ view_count: 256 }) },
    })
    expect(wrapper.find('[data-testid="video-title"]').text()).toBe('示例视频')
    expect(wrapper.find('[data-testid="view-count"]').text()).toBe('256 次播放')
  })

  it('格式化时长（mm:ss）', () => {
    const wrapper = mount(VideoCard, {
      props: { video: makeVideo({ duration: 125 }) },
    })
    expect(wrapper.find('[data-testid="video-duration"]').text()).toBe('2:05')
  })

  it('时长超过一小时时显示 hh:mm:ss', () => {
    const wrapper = mount(VideoCard, {
      props: { video: makeVideo({ duration: 3661 }) },
    })
    expect(wrapper.find('[data-testid="video-duration"]').text()).toBe('1:01:01')
  })

  it('is_liked 时显示已赞角标', () => {
    const wrapper = mount(VideoCard, {
      props: { video: makeVideo({ is_liked: true }) },
    })
    expect(wrapper.find('[data-testid="liked-flag"]').exists()).toBe(true)
  })

  it('默认非编辑态点击 emit click', async () => {
    const wrapper = mount(VideoCard, {
      props: { video: makeVideo() },
    })
    await wrapper.find('[data-testid="video-card"]').trigger('click')
    expect(wrapper.emitted('click')).toBeTruthy()
    expect((wrapper.emitted('click')![0][0] as Video).hash).toBe('abc123')
  })

  it('编辑态点击 emit edit 而非 click', async () => {
    const wrapper = mount(VideoCard, {
      props: { video: makeVideo(), editable: true },
    })
    await wrapper.find('[data-testid="video-card"]').trigger('click')
    expect(wrapper.emitted('edit')).toBeTruthy()
    expect(wrapper.emitted('click')).toBeFalsy()
  })

  it('无缩略图时使用占位图', () => {
    const wrapper = mount(VideoCard, {
      props: { video: makeVideo({ thumbnail: '' }) },
    })
    expect((wrapper.vm as any).thumbnailUrl).toBe('/placeholder.jpg')
  })

  it('渲染标签并点击 emit tagClick', async () => {
    const wrapper = mount(VideoCard, {
      props: {
        video: makeVideo({
          tags: [{ id: 7, name: '动作', path: '动作', level: 1, video_count: 3 }] as any,
        }),
      },
    })
    const tagEls = wrapper.findAll('.card-tag')
    expect(tagEls.length).toBe(1)
    expect(tagEls[0].text()).toBe('动作')
    await tagEls[0].trigger('click')
    expect(wrapper.emitted('tagClick')).toBeTruthy()
  })
})
