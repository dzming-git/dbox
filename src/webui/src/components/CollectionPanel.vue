<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { collectionSetApi } from '../api'

const props = defineProps<{
  itemType: 'video' | 'gallery'
  itemHash: string
}>()

const router = useRouter()
const collections = ref<any[]>([])
const belonging = ref<any[]>([])
const open = ref(false)
const newName = ref('')
const triggerRef = ref<HTMLElement | null>(null)
const ddStyle = ref<Record<string, string>>({})

const load = async () => {
  try {
    const r = await collectionSetApi.getCollections() as any
    collections.value = r?.success ? (r.collections || []) : []
  } catch {
    collections.value = []
  }
  if (props.itemHash) {
    try {
      const b = await collectionSetApi.getByItem(props.itemType, props.itemHash) as any
      belonging.value = b?.success ? (b.collections || []) : []
    } catch {
      belonging.value = []
    }
  }
}

const positionDropdown = () => {
  const el = triggerRef.value
  if (!el) return
  const rect = el.getBoundingClientRect()
  const w = 240
  let left = rect.left
  if (left + w > window.innerWidth - 8) left = window.innerWidth - w - 8
  ddStyle.value = {
    top: `${rect.bottom + 6}px`,
    left: `${Math.max(8, left)}px`,
    width: `${w}px`,
  }
}

const toggle = () => {
  open.value = !open.value
  if (open.value) {
    positionDropdown()
    load()
  }
}
const close = () => { open.value = false }

const addTo = async (colId: number) => {
  if (!props.itemHash) return
  try {
    await (collectionSetApi.addItem(colId, { item_type: props.itemType, item_hash: props.itemHash }) as any)
    await load()
  } catch (e) {
    console.error('加入合集失败', e)
  }
}

const createAndAdd = async () => {
  const name = newName.value.trim()
  if (!name) return
  try {
    const r = await (collectionSetApi.createCollection({ name }) as any)
    if (r?.success) {
      newName.value = ''
      await load()
      if (r.collection) await addTo(r.collection.id)
    }
  } catch (e) {
    console.error('新建合集失败', e)
  }
}

const goCollection = (id: number) => {
  close()
  router.push({ path: '/collections', query: { c: String(id) } })
}

const onResize = () => { if (open.value) positionDropdown() }
onMounted(() => window.addEventListener('resize', onResize))
onBeforeUnmount(() => window.removeEventListener('resize', onResize))
</script>

<template>
  <div class="collection-panel">
    <button ref="triggerRef" class="cp-trigger" type="button" @click.stop="toggle">
          <span class="cp-icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <rect x="3" y="3" width="7" height="7" rx="1"/>
              <rect x="14" y="3" width="7" height="7" rx="1"/>
              <rect x="3" y="14" width="7" height="7" rx="1"/>
              <rect x="14" y="14" width="7" height="7" rx="1"/>
            </svg>
          </span>
          <span class="cp-text">合集</span>
      <span v-if="belonging.length" class="cp-badge">{{ belonging.length }}</span>
    </button>

    <Teleport to="body">
      <div v-if="open" class="cp-overlay" @click="close"></div>
      <div v-if="open" class="cp-dropdown" :style="ddStyle" @click.stop>
        <template v-if="belonging.length">
          <div class="cp-label">所属合集（点击查看）</div>
          <div
            class="cp-chip"
            v-for="c in belonging"
            :key="'b' + c.id"
            @click="goCollection(c.id)"
          >{{ c.name }}</div>
          <div class="cp-divider"></div>
        </template>

        <div class="cp-label">加入合集</div>
        <div v-if="!collections.length" class="cp-empty">暂无合集，请先在下方新建</div>
        <div
          class="cp-item"
          v-for="c in collections"
          :key="c.id"
          @click="addTo(c.id)"
        >{{ c.name }}</div>

        <div class="cp-new">
          <input
            v-model="newName"
            placeholder="新建合集名称"
            @keyup.enter="createAndAdd"
          />
          <button @click="createAndAdd">新建</button>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.collection-panel { display: inline-flex; }
.cp-trigger {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: #2a2a2a;
  border: 1px solid #333;
  color: #ccc;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}
.cp-trigger:hover { background: #333; color: #fff; }
.cp-icon { display: inline-flex; align-items: center; }
.cp-icon svg { width: 16px; height: 16px; }
.cp-badge {
  background: #2196F3;
  color: #fff;
  border-radius: 10px;
  font-size: 11px;
  padding: 0 6px;
  line-height: 16px;
}
.cp-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: transparent;
}
.cp-dropdown {
  position: fixed;
  z-index: 2001;
  background: #2a2a2a;
  border: 1px solid #444;
  border-radius: 10px;
  padding: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
  max-height: 70vh;
  overflow-y: auto;
}
.cp-label {
  font-size: 12px;
  color: #aaa;
  padding: 4px 6px;
  margin-bottom: 4px;
}
.cp-chip {
  display: inline-block;
  margin: 0 6px 6px 0;
  padding: 4px 10px;
  background: #2196F3;
  color: #fff;
  border-radius: 14px;
  font-size: 12px;
  cursor: pointer;
}
.cp-chip:hover { background: #1976D2; }
.cp-divider { height: 1px; background: #3a3a3a; margin: 6px 0; }
.cp-empty { font-size: 12px; color: #777; padding: 6px; }
.cp-item {
  padding: 8px;
  border-radius: 6px;
  font-size: 13px;
  color: #eee;
  cursor: pointer;
}
.cp-item:hover { background: #2196F3; color: #fff; }
.cp-new {
  display: flex;
  gap: 6px;
  margin-top: 8px;
  border-top: 1px solid #3a3a3a;
  padding-top: 8px;
}
.cp-new input {
  flex: 1;
  min-width: 0;
  background: #1a1a1a;
  border: 1px solid #444;
  color: #fff;
  border-radius: 6px;
  padding: 6px 8px;
  font-size: 13px;
}
.cp-new button {
  background: #2196F3;
  border: none;
  color: #fff;
  border-radius: 6px;
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
}
.cp-new button:hover { background: #1976D2; }
</style>
