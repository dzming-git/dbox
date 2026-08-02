<script setup lang="ts">
import WatchLaterButton from './WatchLaterButton.vue'

const props = defineProps<{
  type: 'post' | 'text'
  item: any
  title: string
  meta?: string[]
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
    class="plain-list-row"
    :class="type"
    @click="onRowClick"
  >
    <div class="list-info">
      <h3 class="list-title" :title="title">{{ title }}</h3>
      <div class="list-meta">
        <span v-for="(m, i) in meta" :key="i" class="list-meta-item">{{ m }}</span>
      </div>
      <slot />
    </div>

    <div class="list-actions">
      <WatchLaterButton
        v-if="!editMode"
        variant="compact"
        :type="type"
        :id="String(item.id)"
        :title="title"
        :thumbnail="item.cover_url"
      />
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
.plain-list-row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 12px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
}
.plain-list-row:hover {
  background: var(--bg-surface-2);
}

.list-info {
  flex: 1;
  min-width: 0;
}

.list-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--text-primary);
  margin: 0 0 4px 0;
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
  gap: 6px;
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

/* 移动端：标题占满，操作列只含小图标，不撑开 */
@media (max-width: 600px) {
  .plain-list-row {
    gap: 10px;
    padding: 8px 10px;
  }
  .list-title {
    font-size: 15px;
    line-height: 1.4;
  }
  .list-actions {
    width: auto;
  }
}
</style>
