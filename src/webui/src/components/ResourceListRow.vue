<script setup lang="ts">
import WatchLaterButton from './WatchLaterButton.vue'

const props = defineProps<{
  type: 'video' | 'gallery'
  item: any
  thumbUrl: string
  meta?: string[]
  badge?: string
  editMode?: boolean
}>()

const emit = defineEmits<{
  (e: 'click', item: any): void
  (e: 'edit', item: any): void
}>()

const onRowClick = () => {
  if (props.editMode) emit('edit', props.item)
  else emit('click', props.item)
}
</script>

<template>
  <div
    class="resource-list-row"
    :class="type"
    @click="onRowClick"
  >
    <div class="list-thumb" @click.stop="onRowClick">
      <img :src="thumbUrl" :alt="item.title" loading="lazy" class="list-thumb-img" @error="(e:any)=>e.target.src='/placeholder.jpg'" />
      <span class="list-badge" v-if="badge">{{ badge }}</span>
      <WatchLaterButton
        v-if="!editMode"
        variant="overlay"
        :type="type"
        :id="item.hash"
        :title="item.title"
        :thumbnail="item.thumbnail || item.cover_url"
      />
    </div>

    <div class="list-info">
      <h3 class="list-title" :title="item.title">{{ item.title }}</h3>
      <div class="list-meta">
        <span v-for="(m, i) in meta" :key="i" class="list-meta-item">{{ m }}</span>
      </div>
    </div>

    <div class="list-actions">
      <button
        v-if="editMode"
        class="list-action-btn edit"
        @click.stop="emit('edit', item)"
        title="编辑"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>
        </svg>
      </button>
    </div>
  </div>
</template>

<style scoped>
.resource-list-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 8px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
}
.resource-list-row:hover {
  background: var(--bg-surface-2);
}

.list-thumb {
  position: relative;
  width: 160px;
  flex-shrink: 0;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border-radius: 8px;
  background: #000;
}
/* 图集封面偏竖版，用 3/4 比例更合适 */
.resource-list-row.gallery .list-thumb {
  aspect-ratio: 3 / 4;
}
.list-thumb-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

.list-badge {
  position: absolute;
  bottom: 6px;
  right: 6px;
  background: rgba(0, 0, 0, 0.75);
  color: var(--text-on-accent);
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
}

.list-info {
  flex: 1;
  min-width: 0;
}

.list-title {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0 0 6px 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.list-meta {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 12px;
  color: var(--text-tertiary);
  flex-wrap: wrap;
}

.list-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
  justify-content: flex-end;
}

.list-action-btn {
  width: 30px;
  height: 30px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-surface-hover);
  border: none;
  border-radius: 50%;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s;
}
.list-action-btn:hover {
  color: var(--accent);
}

/* 列表缩略图本就小，缩小右上角稍后再看浮层，避免喧宾夺主 */
.list-thumb :deep(.watch-later-btn.overlay) {
  width: 22px;
  height: 22px;
  top: 4px;
  right: 4px;
  opacity: 0.8;
  background: rgba(0, 0, 0, 0.35);
  backdrop-filter: blur(1px);
}
.list-thumb :deep(.watch-later-btn.overlay) :deep(.wl-icon),
.list-thumb :deep(.watch-later-btn.overlay) svg {
  width: 12px;
  height: 12px;
}

/* 移动端：缩略图收窄让位标题，操作列普通模式不占位，标题占满 */
@media (max-width: 600px) {
  .resource-list-row {
    gap: 10px;
    padding: 8px 10px;
    align-items: stretch;
  }
  .resource-list-row .list-thumb {
    width: 92px;
    align-self: center;
  }
  .list-info {
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  .list-title {
    font-size: 15px;
    line-height: 1.4;
    margin: 0 0 4px 0;
  }
  /* 普通模式操作列不占位，标题占满；仅编辑模式显示编辑按钮 */
  .list-actions {
    display: none;
  }
  .list-actions:has(.list-action-btn) {
    display: flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: auto;
    gap: 6px;
  }
}
</style>
