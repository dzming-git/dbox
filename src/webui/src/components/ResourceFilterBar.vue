<script setup lang="ts">
/**
 * 资源筛选栏（通用件）：媒体类型 tabs + 筛选入口 + 筛选项面板。
 *
 * 为什么抽出来：首页几种资源原先各写一套筛选——视频一套（面板式）、
 * 图集一套（平铺式），字段高度重叠（排序/顺序/资源库/显示方式）却两处维护，
 * 样式与交互已经各自走偏；文本、帖子更是想加筛选就得再抄一遍。
 * 这里把**通用维度**收敛成一份，资源特有的维度（合集、时长、未看天数、
 * 标签树……）通过插槽注入 —— 新增资源类型不必再实现一遍筛选 UI。
 *
 * 用法：
 *   <ResourceFilterBar :tabs="[...]" :tab="mediaTab" @tab-change="..."
 *                      :sorts="..." :sort="..." ...>
 *     <template #extra><MyResourceOnlyFilters /></template>
 *     <template #actions><button>…</button></template>
 *   </ResourceFilterBar>
 */
import { ref, computed } from 'vue'

interface Tab { key: string; label: string }
interface Option { value: any; label: string }

const props = withDefaults(defineProps<{
  /** 面板展开状态（受控：配合 v-model:open，父级可据它联动面板外的内容） */
  open?: boolean
  /** 媒体类型 tab（不传则不渲染 tabs 区） */
  tabs?: Tab[]
  /** 当前选中的 tab */
  tab?: string
  /** 排序字段选项 */
  sorts?: Option[]
  sort?: string
  order?: 'asc' | 'desc'
  /** 资源库（范围维度） */
  libraries?: { id: any; name: string }[]
  libraryId?: any
  /** 搜索关键词；不传则不显示搜索行 */
  keyword?: string
  showSearch?: boolean
  /** 显示方式 */
  viewMode?: 'grid' | 'list'
  showView?: boolean
  /** 生效中的筛选条件数：收起时也要能看出「列表被筛过」 */
  activeCount?: number
}>(), {
  open: false,
  tabs: () => [],
  sorts: () => [],
  libraries: () => [],
  viewMode: 'grid',
  showSearch: true,
  showView: true,
  activeCount: 0,
})

const emit = defineEmits<{
  (e: 'update:open', v: boolean): void
  (e: 'tab-change', v: string): void
  (e: 'sort-change', v: string): void
  (e: 'order-change', v: string): void
  (e: 'library-change', v: any): void
  (e: 'search', v: string): void
  (e: 'clear-search'): void
  (e: 'view-change', v: 'grid' | 'list'): void
}>()

// 受控开合：父级用 v-model:open，这样面板外的内容（如标签树）也能据它渲染
const open = computed({
  get: () => props.open,
  set: (v: boolean) => emit('update:open', v),
})

// 搜索框是「回车才生效」的语义（与后端在当前结果内搜索一致），
// 所以内部维护 draft，提交时再抛给父级。
const draft = ref(props.keyword || '')
const onSearchInput = (e: Event) => { draft.value = (e.target as HTMLInputElement).value }
const submitSearch = () => emit('search', draft.value.trim())
const clearSearch = () => { draft.value = ''; emit('clear-search') }

const onLibrary = (e: Event) => {
  const v = (e.target as HTMLSelectElement).value
  emit('library-change', v === '' ? null : v)
}

const hasTabs = computed(() => props.tabs.length > 0)
</script>

<template>
  <div class="rf">
    <!-- 顶栏：默认只保留「媒体类型 + 筛选入口」一行 -->
    <div class="rf-topbar">
      <div v-if="hasTabs" class="rf-tabs">
        <button
          v-for="t in tabs"
          :key="t.key"
          class="rf-tab"
          :class="{ active: tab === t.key }"
          @click="emit('tab-change', t.key)"
        >{{ t.label }}</button>
      </div>
      <button
        class="rf-toggle"
        :class="{ active: open, has: activeCount > 0 }"
        :title="open ? '收起筛选' : '展开筛选'"
        data-testid="filter-toggle"
        @click="open = !open"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M3 5h18l-7 8v6l-4 2v-8L3 5z"/>
        </svg>
        <span>筛选</span>
        <span v-if="activeCount > 0" class="rf-badge">{{ activeCount }}</span>
        <svg class="rf-chev" :class="{ open }" width="14" height="14" viewBox="0 0 24 24"
             fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 6l6 6-6 6"/>
        </svg>
      </button>
    </div>

    <!-- 筛选项面板：默认收起 -->
    <div v-if="open" class="rf-panel" data-testid="filter-panel">
      <div v-if="showSearch" class="rf-row">
        <span class="rf-label">搜索</span>
        <div class="rf-search">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7"/><line x1="16.5" y1="16.5" x2="21" y2="21"/>
          </svg>
          <input
            :value="draft"
            type="text"
            placeholder="在当前结果中搜索"
            @input="onSearchInput"
            @keyup.enter="submitSearch"
          />
          <button v-if="draft" class="rf-clear-x" title="清除关键词" @click="clearSearch">×</button>
        </div>
      </div>

      <div class="rf-row">
        <span class="rf-label">排序</span>
        <select class="rf-select" :value="sort" @change="emit('sort-change', ($event.target as HTMLSelectElement).value)">
          <option v-for="o in sorts" :key="o.value" :value="o.value">{{ o.label }}</option>
        </select>
        <select class="rf-select" :value="order" @change="emit('order-change', ($event.target as HTMLSelectElement).value)">
          <option value="desc">倒序</option>
          <option value="asc">正序</option>
        </select>
      </div>

      <div class="rf-row">
        <span class="rf-label">范围</span>
        <select class="rf-select" :value="libraryId ?? ''" @change="onLibrary">
          <option value="">全部资源库</option>
          <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
        </select>
        <!-- 同属「归属」维度的其它控件（如视频的合集） -->
        <slot name="scope" />
      </div>

      <div v-if="showView" class="rf-row">
        <span class="rf-label">显示</span>
        <div class="rf-viewtoggle">
          <button class="rf-viewbtn" :class="{ active: viewMode === 'grid' }"
                  title="缩略图" @click="emit('view-change', 'grid')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
            <span class="rf-viewtext">缩略图</span>
          </button>
          <button class="rf-viewbtn" :class="{ active: viewMode === 'list' }"
                  title="列表" @click="emit('view-change', 'list')">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/>
              <line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/>
              <line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/>
            </svg>
            <span class="rf-viewtext">列表</span>
          </button>
        </div>
      </div>

      <!-- 资源特有的筛选项（视频：合集/时长/未看；图集：标签…） -->
      <slot name="extra" />

      <div class="rf-row rf-actions">
        <slot name="actions" />
        <button class="rf-btn" @click="open = false">收起</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.rf { display: block; }

.rf-topbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.rf-tabs {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-default);
  border-radius: 10px;
  padding: 4px 6px;
  flex-shrink: 0;
}
.rf-tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 5px 16px;
  border: none;
  background: transparent;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.2;
  border-radius: 7px;
  cursor: pointer;
  transition: all 0.2s;
}
.rf-tab:hover { color: var(--accent); background: rgba(255, 255, 255, 0.06); }
.rf-tab.active { background: var(--accent); color: var(--text-on-accent); }

.rf-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border: 1px solid var(--border-default);
  border-radius: 10px;
  background: var(--bg-surface);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
  flex-shrink: 0;
  transition: color 0.2s, border-color 0.2s, background 0.2s;
}
.rf-toggle:hover { color: var(--accent); }
.rf-toggle.active { background: var(--bg-surface-hover); color: var(--text-primary); }
/* 有筛选生效时高亮：面板收起后也要能看出「列表被筛过」 */
.rf-toggle.has { color: var(--accent); border-color: var(--accent); }
.rf-badge {
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--accent);
  color: var(--text-on-accent);
  font-size: 11px;
  line-height: 16px;
  text-align: center;
}
.rf-chev { transition: transform 0.2s; }
.rf-chev.open { transform: rotate(180deg); }

.rf-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 12px;
  padding: 12px 14px;
  margin-bottom: 14px;
}
.rf-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
/* 固定宽度的行标签，让各行的控件左边缘对齐 */
.rf-label { flex: 0 0 38px; font-size: 12px; color: var(--text-tertiary); }
.rf-actions { border-top: 1px dashed var(--border-default); padding-top: 10px; }

.rf-select {
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  color: var(--text-primary);
  font-size: 13px;
  padding: 6px 8px;
  max-width: 100%;
}

.rf-search {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 180px;
  background: var(--bg-surface-hover);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  padding: 5px 8px;
  color: var(--text-tertiary);
}
.rf-search input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-size: 13px;
  min-width: 0;
}
.rf-clear-x {
  background: transparent;
  border: none;
  color: var(--text-tertiary);
  font-size: 15px;
  cursor: pointer;
  line-height: 1;
}

.rf-viewtoggle { display: inline-flex; gap: 6px; }
.rf-viewbtn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: var(--bg-surface-hover);
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}
.rf-viewbtn.active { background: var(--accent); color: var(--text-on-accent); border-color: var(--accent); }

.rf-btn {
  padding: 5px 12px;
  border: 1px solid var(--border-default);
  border-radius: 8px;
  background: transparent;
  color: var(--text-secondary);
  font-size: 13px;
  cursor: pointer;
}
.rf-btn:hover:not(:disabled) { color: var(--accent); }
.rf-btn:disabled { opacity: 0.5; cursor: default; }

@media (max-width: 640px) {
  .rf-tab { padding: 5px 10px; font-size: 13px; }
  .rf-label { flex: 0 0 auto; }
  .rf-viewbtn .rf-viewtext { display: none; }
}
</style>
