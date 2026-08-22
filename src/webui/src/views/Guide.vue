<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()

// 已展开的功能条目 id 集合（默认全部折叠，避免信息过载）
const openSet = ref<Set<string>>(new Set())

function toggle(secTitle: string, idx: number) {
  const key = `${secTitle}-${idx}`
  const next = new Set(openSet.value)
  next.has(key) ? next.delete(key) : next.add(key)
  openSet.value = next
}
function isOpen(secTitle: string, idx: number) {
  return openSet.value.has(`${secTitle}-${idx}`)
}

const sections = [
  {
    title: '视频浏览',
    icon: '🎬',
    desc: '发现与播放你的内容',
    items: [
      { text: '首页内容流', tip: '顶部「视频 / 合集 / 帖子 / 文本」标签切换内容类型；首页按更新时间倒序排列，下拉可加载更多。' },
      { text: '进入播放页', tip: '点击视频卡片进入播放页，卡片显示封面、标题、时长（若有）；进入后自动记录观看历史并定位到上次进度。' },
      { text: '推荐与关联', tip: '播放页下方展示推荐视频：手机端自动单列自适应、PC 端多列网格，可左右滑动或滚动浏览，无需切换页面。' },
      { text: '按标签筛选', tip: '视频页顶部「标签」入口打开标签面板，支持多级标签（如 动物/猫/纯白色猫），勾选后在筛选维度内过滤。' },
      { text: '合集连续播放', tip: '首页「合集」标签查看已创建的合集，点开可连续播放合集内全部视频。' },
    ],
  },
  {
    title: '交互操作',
    icon: '👍',
    desc: '点赞、收藏与跟进',
    items: [
      { text: '点赞 / 不喜欢 / 收藏', tip: '登录后操作保存在账号下，跨设备实时同步；「不喜欢」内容会自动从推荐中排除。' },
      { text: '稍后再看', tip: '播放页或卡片上的「稍后再看」按钮标记；导航栏「稍后再看」入口显示数量角标，点击进入列表集中观看，看完可单条移除。' },
      { text: '历史记录', tip: '自动记录每个视频的观看进度与最后观看时间；「历史」页按时间分组（今天/昨天/更早），可继续上次进度播放或批量删除。' },
      { text: '标签管理', tip: '视频页「标签」面板可创建多级标签并关联到视频；标签较多时面板支持滚动查找，可完整下滑选择。' },
    ],
  },
  {
    title: '资源与内容',
    icon: '🗂️',
    desc: '多模式资源管理',
    items: [
      { text: '多模式资源库', tip: '同一份资源可同时属于多个模式（视频/图集/帖子/文本）而不重复存储；资源库按物理存储分组，模式按展示维度分组，互不耦合。' },
      { text: '图集', tip: '由多张图片组成的资源，可点赞/收藏/删除；操作即时反馈，无需刷新即可看到状态变化。' },
      { text: '帖子', tip: '自由引用多个视频/图片集/文本资源的混合内容，可在管理后台或首页「帖子」标签创建与编辑，支持拖拽排序引用顺序。' },
      { text: '文本', tip: '纯文本或说明类内容，作为独立模式在首页「文本」标签展示，可被帖子引用。' },
      { text: '资源库管理', tip: '管理后台「资源」标签查看各资源库占用；下载/扫描时指定目标资源库，资源即按库归集。' },
    ],
  },
  {
    title: '上传与管理',
    icon: '📤',
    desc: '内容入库与运维',
    items: [
      { text: '上传视频', tip: '用户下拉菜单 → 上传视频；支持拖拽与批量选择，上传后自动计算内容指纹入库（与文件名无关，重命名不影响去重）。' },
      { text: '管理后台', tip: '用户下拉菜单 → 管理；包含仪表板、资源管理、服务管理、系统监控、日志、拓展脚本等模块，管理员可见。' },
      { text: '扩展管理', tip: '用户下拉菜单 → 扩展管理；安装与运行拓展插件（如 X 媒体下载器）。插件参数支持「保存为默认」，下次自动填入。' },
      { text: '任务管理器', tip: '导航栏 → 任务；集中查看所有后台任务（下载、转码、扫描等）的状态与失败原因，便于跟进。' },
      { text: '电脑关机控制', tip: '管理后台提供关机功能，支持「立即关机 / 定时关机 / 全部任务结束后关机」三种模式。' },
    ],
  },
  {
    title: '系统监控',
    icon: '📈',
    desc: '实时运行状态',
    items: [
      { text: '查看系统状态', tip: '管理后台 → 系统监控标签；每 3 秒自动刷新，展示 CPU 使用率（含每核心）、内存占用、各磁盘使用率与可用空间。' },
      { text: '指标含义', tip: 'CPU 卡片含核心数与当前频率；内存卡片显示已用/总计/可用；磁盘卡片按盘符分别展示，颜色随使用率由绿转黄转红。' },
      { text: '手动刷新', tip: '点击「刷新」按钮立即拉取最新指标；长时间停留页面会自动持续轮询，离开页面自动停止以节省资源。' },
    ],
  },
  {
    title: '反馈与设置',
    icon: '💬',
    desc: '偏好与沟通',
    items: [
      { text: '意见反馈', tip: '用户下拉菜单 → 反馈；可选择问题类型（缺陷/建议/其他），内容非必填、不限制字数，提交后可在列表中查看处理进度。' },
      { text: '设置', tip: '用户下拉菜单 → 设置；可配置个人偏好；「清除所有互动数据」会清空当前账号的点赞/收藏/历史等（不可恢复），请谨慎操作。' },
      { text: '功能指引', tip: '本页面即功能指引，按模块分点列出所有功能的入口与细节；新功能会持续补充。' },
    ],
  },
]
</script>

<template>
  <div class="guide-page">
    <!-- Hero 区 -->
    <header class="guide-hero">
      <div class="hero-icon">🧭</div>
      <h1>功能指引</h1>
      <p class="hero-sub">一份清晰、可交互的 DBox 使用指南 —— 点击任意条目展开细节。</p>
    </header>

    <!-- 模块卡片网格 -->
    <div class="guide-grid">
      <section
        v-for="sec in sections"
        :key="sec.title"
        class="module-card"
      >
        <div class="module-head">
          <span class="module-icon">{{ sec.icon }}</span>
          <div class="module-titles">
            <h2 class="module-title">{{ sec.title }}</h2>
            <p class="module-desc">{{ sec.desc }}</p>
          </div>
        </div>

        <ul class="module-items">
          <li
            v-for="(item, idx) in sec.items"
            :key="idx"
            class="feature"
            :class="{ open: isOpen(sec.title, idx) }"
          >
            <button
              class="feature-trigger"
              @click="toggle(sec.title, idx)"
              :aria-expanded="isOpen(sec.title, idx)"
            >
              <span class="feature-text">{{ item.text }}</span>
              <span class="feature-arrow">›</span>
            </button>
            <transition name="expand">
              <p v-if="isOpen(sec.title, idx)" class="feature-tip">{{ item.tip }}</p>
            </transition>
          </li>
        </ul>
      </section>
    </div>

    <footer class="guide-footer">
      <button class="back-btn" @click="router.push('/')">返回首页</button>
    </footer>
  </div>
</template>

<style scoped>
.guide-page {
  max-width: 1100px;
  margin: 0 auto;
  padding: 40px 20px 64px;
}

/* Hero */
.guide-hero {
  text-align: center;
  margin-bottom: 36px;
}
.hero-icon {
  font-size: 44px;
  line-height: 1;
  margin-bottom: 12px;
}
.guide-hero h1 {
  font-size: 30px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 8px;
}
.hero-sub {
  color: var(--text-secondary);
  font-size: 15px;
  margin: 0 auto 20px;
  max-width: 520px;
  line-height: 1.6;
}

/* 卡片网格 */
.guide-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}
.module-card {
  background: var(--bg-surface);
  border: 1px solid var(--bg-surface-2);
  border-radius: 14px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  transition: box-shadow .25s, transform .25s;
}
.module-card:hover {
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.06);
  transform: translateY(-2px);
}
.module-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 14px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface-2);
}
.module-icon {
  font-size: 26px;
  flex-shrink: 0;
}
.module-titles {
  min-width: 0;
}
.module-title {
  font-size: 17px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}
.module-desc {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 2px 0 0;
}

/* 功能条目（可展开） */
.module-items {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.feature {
  border-radius: 10px;
  background: var(--bg-surface-2);
  overflow: hidden;
}
.feature.open {
  background: var(--accent-soft);
}
.feature-trigger {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 11px 14px;
  background: none;
  border: none;
  cursor: pointer;
  text-align: left;
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}
.feature-arrow {
  color: var(--text-secondary);
  font-size: 20px;
  line-height: 1;
  transition: transform .25s, color .25s;
  flex-shrink: 0;
}
.feature.open .feature-arrow {
  transform: rotate(90deg);
  color: var(--accent);
}
.feature-tip {
  margin: 0;
  padding: 0 14px 12px;
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-secondary);
}

/* 展开动画 */
.expand-enter-active,
.expand-leave-active {
  transition: opacity .2s ease;
}
.expand-enter-from,
.expand-leave-to {
  opacity: 0;
}

/* 底部 */
.guide-footer {
  text-align: center;
  margin-top: 40px;
}
.back-btn {
  padding: 11px 32px;
  background: var(--accent);
  color: var(--text-on-accent);
  border: none;
  border-radius: 999px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity .2s, transform .2s;
}
.back-btn:hover {
  opacity: .9;
  transform: translateY(-1px);
}

@media (max-width: 600px) {
  .guide-page { padding: 24px 14px 48px; }
  .guide-hero h1 { font-size: 24px; }
  .guide-grid {
    grid-template-columns: 1fr;
    gap: 16px;
  }
}
</style>
