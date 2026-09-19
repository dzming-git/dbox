<template>
  <div class="notif-page">
    <div class="notif-page-head">
      <h1>通知</h1>
      <button v-if="store.unread > 0" class="notif-markall" @click="store.markAllRead()">全部已读</button>
    </div>

    <div v-if="loading" class="notif-state">加载中…</div>
    <div v-else-if="!store.items.length" class="notif-state">暂无通知</div>

    <div v-else class="notif-list">
      <!-- 通用富卡片：图片/摘要/跳转/操作均由插件在 payload 中提供，框架只做渲染 -->
      <div v-for="n in store.items" :key="n.id" class="notif-item"
           :class="{ unread: !n.read }" @click="openItem(n)">
        <img v-if="n.payload && n.payload.image" class="notif-thumb"
             :src="n.payload.image" alt="" loading="lazy" />
        <div class="notif-body-col">
          <div class="notif-title">{{ n.title }}</div>
          <div v-if="summary(n)" class="notif-summary">{{ summary(n) }}</div>
          <div class="notif-meta">
            <span v-if="n.source" class="notif-source">{{ n.source }}</span>
            <span class="notif-time">{{ formatTime(n.createdAt) }}</span>
          </div>
          <div v-if="n.payload && n.payload.actions && n.payload.actions.length"
               class="notif-actions" @click.stop>
            <button v-for="(a, i) in n.payload.actions" :key="i"
                    class="notif-action" @click="openAction(a)">{{ a.label }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useNotificationStore } from '../stores/notificationStore'
import type { UserNotification } from '../types'

const store = useNotificationStore()
const router = useRouter()
const loading = ref(true)

function summary(n: UserNotification): string {
  const p = (n.payload || {}) as Record<string, any>
  if (p.summary) return String(p.summary)
  return n.body || ''
}
function isInternal(url: string): boolean {
  return url.startsWith('/')
}
function navigate(url: string) {
  if (!url) return
  if (isInternal(url)) router.push(url)
  else window.open(url, '_blank', 'noopener')
}
function openItem(n: UserNotification) {
  const url = (n.payload && (n.payload as Record<string, any>).url) as string | undefined
  if (url) navigate(url)
  if (!n.read) store.markRead(n.id)
}
function openAction(a: { label: string; url: string }) {
  if (a && a.url) navigate(a.url)
}
function formatTime(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString()
}

onMounted(async () => {
  await store.load()
  loading.value = false
})
</script>

<style scoped>
.notif-page {
  max-width: 720px;
  margin: 0 auto;
  padding: 20px 16px 40px;
}
.notif-page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.notif-page-head h1 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}
.notif-markall {
  background: none;
  border: none;
  color: var(--accent, #f97316);
  cursor: pointer;
  font-size: 13px;
}
.notif-state {
  padding: 48px 14px;
  text-align: center;
  color: var(--text-muted, #9ca3af);
}
.notif-list {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--border, #333);
  border-radius: 12px;
  overflow: hidden;
  background: var(--bg-elevated, #1f2937);
}
.notif-item {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border, #2a2a2a);
  cursor: pointer;
}
.notif-item:last-child {
  border-bottom: none;
}
.notif-item.unread {
  background: rgba(249, 115, 22, .08);
}
.notif-thumb {
  width: 56px;
  height: 56px;
  object-fit: cover;
  border-radius: 8px;
  flex: 0 0 auto;
  background: #111;
}
.notif-body-col {
  flex: 1;
  min-width: 0;
}
.notif-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}
.notif-summary {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-muted, #9ca3af);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.notif-meta {
  margin-top: 6px;
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--text-muted, #6b7280);
}
.notif-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.notif-action {
  background: var(--accent, #f97316);
  border: none;
  color: #fff;
  border-radius: 6px;
  padding: 4px 10px;
  font-size: 12px;
  cursor: pointer;
}
</style>
