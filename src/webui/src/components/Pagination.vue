<script setup lang="ts">
const props = defineProps<{
  currentPage: number
  totalPages: number
  total: number
  pageRange: (number | null)[]
}>()

const emit = defineEmits<{
  (e: 'change', page: number): void
}>()

const go = (page: number) => {
  if (page < 1 || page > props.totalPages || page === props.currentPage) return
  emit('change', page)
}
</script>

<template>
  <div class="pagination">
    <button class="page-btn" :disabled="currentPage <= 1" @click="go(1)">首页</button>
    <button class="page-btn" :disabled="currentPage <= 1" @click="go(currentPage - 1)">‹ 上一页</button>
    <template v-for="p in pageRange" :key="String(p) + '-' + Math.random()">
      <button v-if="p" class="page-btn" :class="{ active: p === currentPage }" @click="go(p)">{{ p }}</button>
      <span v-else class="page-ellipsis">...</span>
    </template>
    <button class="page-btn" :disabled="currentPage >= totalPages" @click="go(currentPage + 1)">下一页 ›</button>
    <button class="page-btn" :disabled="currentPage >= totalPages" @click="go(totalPages)">末页</button>
    <span class="page-info">第 {{ currentPage }} / {{ totalPages }} 页（共 {{ total }} 条）</span>
  </div>
</template>

<style scoped>
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 16px;
  margin-top: 16px;
  background: var(--bg-surface);
  border: 1px solid var(--border-subtle);
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04);
}

.page-btn {
  min-width: 36px;
  height: 36px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.page-btn:hover:not(:disabled) {
  background: var(--bg-surface-hover);
  color: var(--accent);
}

.page-btn:disabled {
  color: var(--text-tertiary);
  cursor: not-allowed;
  opacity: 0.5;
}

.page-btn.active {
  background: var(--accent);
  color: var(--text-on-accent);
  font-weight: 600;
}

.page-ellipsis {
  color: var(--text-tertiary);
  padding: 0 8px;
}

.page-info {
  font-size: 13px;
  color: var(--text-tertiary);
  margin-left: 8px;
}

@media (max-width: 768px) {
  .pagination {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    margin: 0;
    border-radius: 16px 16px 0 0;
    box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.12);
    padding: 12px 16px calc(12px + env(safe-area-inset-bottom, 0px));
    z-index: 100;
  }

  .page-info {
    display: none;
  }
}
</style>
