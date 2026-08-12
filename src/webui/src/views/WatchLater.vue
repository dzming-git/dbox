<script setup lang="ts">
import { computed, onMounted, onActivated, onDeactivated } from 'vue'
import { useRouter } from 'vue-router'
import { useWatchLaterStore, type WatchLaterItem, type WatchLaterType } from '../stores/watchLaterStore'
import { usePullToRefresh } from '../composables/usePullToRefresh'
import { withThumbToken } from '../utils/media'

const router = useRouter()
const store = useWatchLaterStore()

const list = computed(() => store.list)
const count = computed(() => store.count)

const TYPE_PATH: Record<WatchLaterType, string> = {
  video: '/video/',
  gallery: '/gallery/',
  post: '/post/',
  text: '/text/'
}

const typeLabel = (t: WatchLaterType) =>
  ({ video: '视频', gallery: '图集', post: '帖子', text: '文本' }[t] || t)

const thumb = (it: WatchLaterItem) => (it.thumbnail ? withThumbToken(it.thumbnail) : '')

const open = (it: WatchLaterItem) => {
  router.push(TYPE_PATH[it.type] + it.id)
}

const remove = (it: WatchLaterItem) => {
  store.remove(it.type, it.id)
}

const clearAll = () => {
  if (!count.value) return
  if (!confirm('确定要清空「稍后再看」列表吗？')) return
  store.clear()
}

onMounted(() => {
  store.init()
})

// 顶部下拉刷新：重新拉取「稍后再看」列表
const ptr = usePullToRefresh()
function registerPtr() {
  ptr.setHandler(() => store.init())
}
onMounted(registerPtr)
onActivated(registerPtr)
onUnmounted(() => ptr.clearHandler())
onDeactivated(() => ptr.clearHandler())
</script>

<template>
  <div class="wl-page">
    <div class="wl-header">
      <div class="wl-title">
        <h1>稍后再看</h1>
        <span class="wl-count">共 {{ count }} 项</span>
      </div>
      <button v-if="count" class="wl-clear-btn" @click="clearAll">清空</button>
    </div>

    <div v-if="!count" class="wl-empty">
      <svg width="48" height="48" viewBox="0 0 24 24" fill="currentColor" opacity="0.35">
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 14H9V8h2v8zm4 0h-2V8h2v8z"/>
      </svg>
      <p>暂无「稍后再看」内容。</p>
      <p class="wl-empty-hint">在视频、图集、帖子或文本上点「稍后再看」即可加入。</p>
      <div class="wl-empty-rel">
        <span><b>稍后再看</b>：待处理清单，看完即移除</span>
        <span><b>收藏</b>：个人长期保存，跨设备保留</span>
        <span><b>合集</b>：公开整理，可分享给他人</span>
      </div>
    </div>

    <div v-else class="wl-grid">
      <div
        v-for="it in list"
        :key="it.type + ':' + it.id"
        class="wl-card"
        @click="open(it)"
      >
        <div class="wl-card-thumb">
          <img v-if="thumb(it)" :src="thumb(it)" :alt="it.title" />
          <div v-else class="wl-card-ph">{{ typeLabel(it.type) }}</div>
          <span class="wl-card-type">{{ typeLabel(it.type) }}</span>
          <button
            class="wl-card-remove"
            title="移除"
            @click.stop="remove(it)"
          >×</button>
        </div>
        <div class="wl-card-title" :title="it.title">{{ it.title }}</div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.wl-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px 20px 60px;
  color: var(--text-primary);
}
.wl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 22px;
}
.wl-title {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.wl-title h1 {
  font-size: 22px;
  font-weight: 600;
  margin: 0;
}
.wl-count {
  font-size: 13px;
  color: var(--text-secondary);
}
.wl-clear-btn {
  background: transparent;
  border: 1px solid var(--border-strong);
  color: var(--danger);
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.wl-clear-btn:hover {
  border-color: var(--danger);
  background: rgba(255, 107, 107, 0.1);
}
.wl-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  color: var(--text-secondary);
  text-align: center;
}
.wl-empty p { margin: 6px 0 0; font-size: 15px; }
.wl-empty-hint { font-size: 13px !important; color: var(--text-tertiary) !important; }
.wl-empty-rel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 18px;
  padding: 14px 18px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  font-size: 13px;
  color: var(--text-tertiary);
}
.wl-empty-rel b { color: var(--text-secondary); }

.wl-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}
.wl-card {
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.15s, border-color 0.15s;
}
.wl-card:hover {
  transform: translateY(-3px);
  border-color: var(--border-strong);
}
.wl-card-thumb {
  position: relative;
  aspect-ratio: 16 / 9;
  background: var(--bg-surface-2);
  overflow: hidden;
}
.wl-card-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.wl-card-ph {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: var(--text-tertiary);
  background: var(--bg-surface-hover);
}
.wl-card-type {
  position: absolute;
  left: 8px;
  bottom: 8px;
  background: rgba(0, 0, 0, 0.65);
  color: var(--text-on-accent);
  font-size: 11px;
  padding: 2px 7px;
  border-radius: 6px;
}
.wl-card-remove {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 26px;
  height: 26px;
  border: none;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.6);
  color: var(--text-secondary);
  font-size: 17px;
  line-height: 1;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.15s, color 0.15s;
}
.wl-card-remove:hover {
  background: #ff6b6b;
  color: var(--accent);
}
.wl-card-title {
  padding: 10px 12px;
  font-size: 14px;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
