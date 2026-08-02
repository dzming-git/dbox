<script setup lang="ts">
import { useRouter } from 'vue-router'
const router = useRouter()

const sections = [
  {
    title: '视频浏览',
    icon: '🎬',
    items: [
      { text: '首页展示最新视频、合集、帖子、文本', tip: '' },
      { text: '点击视频卡片进入播放页', tip: '' },
      { text: '推荐视频在播放页下方（手机端自动适配）', tip: '' },
      { text: '支持按标签、合集筛选', tip: '' },
    ],
  },
  {
    title: '交互操作',
    icon: '👍',
    items: [
      { text: '点赞 / 不喜欢 / 收藏', tip: '登录后操作，跨设备同步' },
      { text: '稍后再看：标记后可在稍后再看列表查看', tip: '' },
      { text: '历史记录自动记录观看进度', tip: '' },
      { text: '标签管理：为视频添加/编辑标签', tip: '' },
    ],
  },
  {
    title: '上传与管理',
    icon: '📤',
    items: [
      { text: '上传视频：用户下拉菜单 → 上传视频', tip: '支持拖拽、批量' },
      { text: '管理后台：用户下拉菜单 → 管理', tip: '仪表板 / 资源 / 服务 / 日志等' },
      { text: '拓展脚本：用户下拉菜单 → 拓展脚本', tip: '运行外部下载/处理任务' },
      { text: '任务管理器：导航栏 → 任务', tip: '查看所有任务状态与待处理事项' },
    ],
  },
  {
    title: '反馈与帮助',
    icon: '💬',
    items: [
      { text: '意见反馈：用户下拉菜单 → 反馈', tip: '提交建议或报告问题' },
      { text: '系统监控：管理后台 → 系统监控标签', tip: '查看 CPU / 内存 / 磁盘状态' },
      { text: '设置：用户下拉菜单 → 设置', tip: '个人偏好配置' },
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
  color: #e6e6e6;
  margin-bottom: 8px;
}
.guide-subtitle {
  color: #888;
  font-size: 15px;
}
.guide-sections {
  display: flex;
  flex-direction: column;
  gap: 24px;
}
.guide-section {
  background: #1a1a24;
  border: 1px solid #2a2a38;
  border-radius: 12px;
  padding: 24px;
}
.section-title {
  font-size: 18px;
  color: #e6e6e6;
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
  background: #14141c;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.5;
}
.item-text {
  color: #c9d1d9;
  white-space: pre-wrap;
}
.item-tip {
  color: #6b7a8f;
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
