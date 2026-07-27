<script setup lang="ts">
import { computed } from 'vue'
import { useWatchLaterStore, type WatchLaterType } from '../stores/watchLaterStore'

const props = defineProps<{
  type: WatchLaterType
  id: string
  title: string
  thumbnail?: string
  // variant: 'overlay' 用于预览图角标，'bar' 用于详情页按钮
  variant?: 'overlay' | 'bar'
}>()

const store = useWatchLaterStore()
const active = computed(() => store.has(props.type, props.id))

const onToggle = () => {
  store.toggle({
    type: props.type,
    id: props.id,
    title: props.title,
    thumbnail: props.thumbnail,
  })
}
</script>

<template>
  <button
    type="button"
    class="watch-later-btn"
    :class="[variant || 'bar', { active }]"
    :title="active ? '取消稍后再看' : '稍后再看'"
    @click.stop.prevent="onToggle"
  >
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </svg>
    <span v-if="variant === 'bar'" class="wl-label">{{ active ? '稍后再看' : '稍后再看' }}</span>
  </button>
</template>

<style scoped>
.watch-later-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  cursor: pointer;
  color: #bbb;
  background: rgba(0, 0, 0, 0.45);
  transition: color 0.15s, background 0.15s;
}
.watch-later-btn:hover {
  color: #fff;
}
.watch-later-btn.active {
  color: #ffb300;
}
/* 预览图角标样式 */
.watch-later-btn.overlay {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 32px;
  height: 32px;
  border-radius: 50%;
  justify-content: center;
  z-index: 3;
}
/* 详情页按钮样式 */
.watch-later-btn.bar {
  padding: 8px 14px;
  border-radius: 10px;
  background: #2a2a2a;
  font-size: 14px;
}
.watch-later-btn.bar:hover {
  background: #333;
}
.watch-later-btn.bar.active {
  background: rgba(255, 179, 0, 0.15);
}
.wl-label {
  font-size: 14px;
}
</style>
