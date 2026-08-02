<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()

const sections = [
  {
    title: '视频浏览',
    icon: '🎬',
    items: [
      { text: '首页展示最新视频、合集、帖子、文本', tip: '顶部「视频 / 合集 / 帖子 / 文本」标签切换内容类型；首页按更新时间倒序排列，下拉可加载更多' },
      { text: '点击视频卡片进入播放页', tip: '卡片显示封面、标题、时长（若有）；点击后自动记录观看历史并定位到上次进度' },
      { text: '推荐视频在播放页下方', tip: '手机端自动单列自适应、PC 端多列网格；可左右滑动或滚动浏览，无需切换页面' },
      { text: '按标签筛选', tip: '视频页顶部「标签」入口打开标签面板，支持多级标签（如 动物/猫/纯白色猫），勾选后在筛选维度（视频/图集/帖子）内过滤' },
      { text: '合集浏览', tip: '首页「合集」标签查看已创建的合集，点开可连续播放合集内全部视频' },
    ],
  },
  {
    title: '交互操作',
    icon: '👍',
    items: [
      { text: '点赞 / 不喜欢 / 收藏', tip: '登录后操作：点赞、不喜欢、收藏均保存在账号下，跨设备实时同步；不喜欢内容会自动从推荐中排除' },
      { text: '稍后再看', tip: '播放页或卡片上的「稍后再看」按钮标记；顶部导航栏的「稍后再看」入口显示数量角标，点击进入列表集中观看，看完可单条移除' },
      { text: '历史记录', tip: '自动记录每个视频的观看进度与最后观看时间；「历史」页按时间分组（今天/昨天/更早），可继续上次进度播放或批量删除' },
      { text: '标签管理', tip: '视频页「标签」面板可创建多级标签并关联到视频；手机端标签面板支持滚动查找，已有标签较多时也能完整下滑选择' },
    ],
  },
  {
    title: '资源与内容',
    icon: '🗂️',
    items: [
      { text: '多模式资源库', tip: '同一份资源可同时属于多个模式（视频/图集/帖子/文本）而不重复存储；资源库按物理存储分组，模式按展示维度分组，互不耦合' },
      { text: '图集（图片集）', tip: '由多张图片组成的资源，可点赞/收藏/删除；操作即时反馈，无需刷新即可看到状态变化' },
      { text: '帖子', tip: '自由引用多个视频/图片集/文本资源的混合内容，可在管理后台或首页「帖子」标签创建与编辑，支持拖拽排序引用顺序' },
      { text: '文本', tip: '纯文本或说明类内容，作为独立模式在首页「文本」标签展示，可被帖子引用' },
      { text: '资源库管理', tip: '管理后台「资源」标签查看各资源库占用；下载/扫描时指定目标资源库，资源即按库归集' },
    ],
  },
  {
    title: '上传与管理',
    icon: '📤',
    items: [
      { text: '上传视频', tip: '用户下拉菜单 → 上传视频；支持拖拽与批量选择，上传后自动计算内容指纹入库（与文件名无关，重命名不影响去重）' },
      { text: '管理后台', tip: '用户下拉菜单 → 管理；包含仪表板、资源管理、服务管理、系统监控、日志、拓展脚本等模块，管理员可见' },
      { text: '拓展脚本', tip: '用户下拉菜单 → 拓展脚本；运行外部下载/处理任务（如 X 媒体下载器）。脚本参数支持「保存为默认」，下次自动填入' },
      { text: '任务管理器', tip: '导航栏 → 任务；集中查看所有后台任务（下载、转码、扫描等）的状态与失败原因，便于跟进' },
      { text: '电脑关机控制', tip: '管理后台提供关机功能，支持「立即关机 / 定时关机 / 全部任务结束后关机」三种模式' },
    ],
  },
  {
    title: '系统监控',
    icon: '📈',
    items: [
      { text: '查看系统状态', tip: '管理后台 → 系统监控标签；每 3 秒自动刷新，展示 CPU 使用率（含每核心）、内存占用、各磁盘使用率与可用空间' },
      { text: '指标含义', tip: 'CPU 卡片含核心数与当前频率；内存卡片显示已用/总计/可用；磁盘卡片按盘符分别展示，颜色随使用率由绿转黄转红' },
      { text: '手动刷新', tip: '点击「刷新」按钮立即拉取最新指标；长时间停留页面会自动持续轮询，离开页面自动停止以节省资源' },
    ],
  },
  {
    title: '反馈与设置',
    icon: '💬',
    items: [
      { text: '意见反馈', tip: '用户下拉菜单 → 反馈；可选择问题类型（缺陷/建议/其他），内容非必填、不限制字数，提交后可在列表中查看处理进度' },
      { text: '设置', tip: '用户下拉菜单 → 设置；可配置个人偏好；「清除所有互动数据」会清空当前账号的点赞/收藏/历史等（不可恢复），请谨慎操作' },
      { text: '功能指引', tip: '本页面即功能指引，按模块分点列出所有功能的入口与细节；新功能会持续补充' },
    ],
  },
]
</script>

<template>
  <div class="guide-page">
    <div class="guide-header">
      <h1>功能指引</h1>
      <p class="guide-subtitle">DPlayer 使用指南与功能概览</p>
    </div>

    <div class="guide-sections">
      <div v-for="sec in sections" :key="sec.title" class="guide-section">
        <h2 class="section-title">
          <span class="section-icon">{{ sec.icon }}</span>
          {{ sec.title }}
        </h2>
        <ul class="section-items">
          <li v-for="(item, idx) in sec.items" :key="idx" class="section-item">
            <span class="item-text">{{ item.text }}</span>
            <span v-if="item.tip" class="item-tip">{{ item.tip }}</span>
          </li>
        </ul>
      </div>
    </div>

    <div class="guide-footer">
      <button class="btn-primary" @click="router.push('/')">返回首页</button>
    </div>
  </div>
</template>

<style scoped>
.guide-page {
  max-width: 800px;
  margin: 0 auto;
  padding: 32px 20px 60px;
}
.guide-header {
  text-align: center;
  margin-bottom: 40px;
}
.guide-header h1 {
  font-size: 28px;
  color: var(--text-secondary);
  margin-bottom: 8px;
}
.guide-subtitle {
  color: var(--text-secondary);
  font-size: 15px;
}
.guide-sections {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.guide-section {
  background: var(--bg-surface-hover);
  border: 1px solid var(--bg-surface-2);
  border-radius: 12px;
  padding: 24px;
}
.section-title {
  font-size: 18px;
  color: var(--text-secondary);
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.section-icon {
  font-size: 22px;
}
.section-items {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.section-item {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 8px 12px;
  background: var(--bg-surface);
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.5;
}
.item-text {
  color: var(--text-secondary);
  white-space: pre-wrap;
}
.item-tip {
  color: var(--text-secondary);
  font-size: 12px;
  margin-left: auto;
  flex-shrink: 0;
  white-space: nowrap;
}
.guide-footer {
  text-align: center;
  margin-top: 36px;
}
.btn-primary {
  padding: 10px 28px;
  background: linear-gradient(135deg, #ffb300, #ff8c00);
  color: #111;
  border: none;
  border-radius: 8px;
  font-size: 15px;
  font-weight: 600;
  cursor: pointer;
  transition: opacity .2s;
}
.btn-primary:hover { opacity: .85; }

@media (max-width: 768px) {
  .guide-page { padding: 16px 12px 48px; }
  .guide-header h1 { font-size: 22px; }
  .guide-section { padding: 16px; }
  .section-item { flex-direction: column; gap: 4px; }
  .item-tip { margin-left: 0; }
}
</style>
