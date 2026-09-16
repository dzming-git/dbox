/**
 * 首页媒体类型（tab）定义。
 *
 * 抽成共享常量的原因：tabs 条现在由**各个资源视图自己渲染**（视频在 Home，
 * 图集/文本/帖子在各自组件内），若各处各写一份字面量，增删一种类型就要
 * 找齐所有地方，迟早漏一处。
 *
 * 为什么 tabs 不放在 Home 统一渲染：筛选面板的内容属于各资源自己
 * （图集的排序项、标签列表与视频完全不同）。若 Home 渲染 tabs + 筛选按钮，
 * 子视图再渲染一份自己的筛选栏，同一个页面就会出现两个「筛选」按钮——
 * 这正是之前图集上出现两个按钮的原因。所以改成：**谁的内容，谁的整条工具条**。
 */
export type MediaTab = 'video' | 'gallery' | 'text' | 'mixed'

export const MEDIA_TABS: { key: MediaTab; label: string }[] = [
  { key: 'video', label: '视频' },
  { key: 'gallery', label: '图集' },
  { key: 'text', label: '文本' },
  { key: 'mixed', label: '帖子' },
]
