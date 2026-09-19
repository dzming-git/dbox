<template>
  <div class="notif-bell-wrap">
    <button class="notif-bell nav-link nav-icon-link" :title="'通知'"
            @click="toggle">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor">
        <path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.64-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.63 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/>
      </svg>
      <span>通知</span>
      <span v-if="store.unread > 0" class="notif-badge">{{ store.unread > 99 ? '99+' : store.unread }}</span>
    </button>

    <div v-if="open" class="notif-overlay" @click="close"></div>
    <div v-if="open" class="notif-panel">
      <div class="notif-head">
        <span>通知</span>
        <button v-if="store.unread > 0" class="notif-markall" @click="store.markAllRead()">全部已读</button>
      </div>
      <div class="notif-list">
        <div v-if="!store.items.length" class="notif-empty">暂无通知</div>
        <div v-for="n in store.items" :key="n.id" class="notif-item"
             :class="{ unread: !n.read }" @click="onItemClick(n)">
          <div class="notif-title">{{ n.title }}</div>
          <div v-if="n.body" class="notif-body">{{ n.body }}</div>
          <div class="notif-meta">
            <span v-if="n.source" class="notif-source">{{ n.source }}</span>
            <span class="notif-time">{{ formatTime(n.createdAt) }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useNotificationStore } from '../stores/notificationStore'
import type { UserNotification } from '../types'

const store = useNotificationStore()
const open = ref(false)

function toggle() {
  open.value = !open.value
  if (open.value) store.load()
}
function close() {
  open.value = false
}
function onItemClick(n: UserNotification) {
  if (!n.read) store.markRead(n.id)
  const link = n.payload && n.payload.link
  if (link) window.location.href = link
}
function formatTime(iso: string | null) {
  if (!iso) return ''
  const d = new Date(iso)
  if (isNaN(d.getTime())) return ''
  return d.toLocaleString()
}

onMounted(() => store.load())
</script>

<style scoped>
.notif-bell-wrap {
  position: relative;
  display: inline-flex;
}
.notif-badge {
  position: absolute;
  top: -4px;
  right: -6px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--danger, #ef4444);
  color: #fff;
  font-size: 11px;
  line-height: 16px;
  text-align: center;
}
.notif-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
}
.notif-panel {
  position: absolute;
  top: 48px;
  right: 0;
  width: 320px;
  max-height: 70vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--nav-bg, #1f2937);
  border: 1px solid var(--border, #333);
  border-radius: 10px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, .35);
  z-index: 1001;
}
.notif-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 14px;
  border-bottom: 1px solid var(--border, #333);
  font-weight: 600;
}
.notif-markall {
  background: none;
  border: none;
  color: var(--accent, #f97316);
  cursor: pointer;
  font-size: 13px;
}
.notif-list {
  overflow-y: auto;
}
.notif-empty {
  padding: 28px 14px;
  text-align: center;
  color: var(--text-muted, #9ca3af);
}
.notif-item {
  padding: 10px 14px;
  border-bottom: 1px solid var(--border, #2a2a2a);
  cursor: pointer;
}
.notif-item.unread {
  background: rgba(249, 115, 22, .08);
}
.notif-title {
  font-size: 14px;
  font-weight: 600;
}
.notif-body {
  margin-top: 4px;
  font-size: 13px;
  color: var(--text-muted, #9ca3af);
  white-space: pre-wrap;
}
.notif-meta {
  margin-top: 6px;
  display: flex;
  gap: 10px;
  font-size: 11px;
  color: var(--text-muted, #6b7280);
}
</style>
