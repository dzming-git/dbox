<template>
  <div class="subs-page">
    <h2 class="subs-title">订阅管理</h2>
    <p class="subs-hint">
      订阅你关注的来源（X 账号 / pixiv 画师等）。对应扩展会在拉取到新内容后，
      经平台通知接口提醒你。
    </p>

    <div class="subs-add">
      <select v-model="form.sourceType" class="subs-input">
        <option value="x">X（Twitter）</option>
        <option value="pixiv">pixiv</option>
      </select>
      <input v-model.trim="form.sourceId" class="subs-input" placeholder="来源 ID / handle，如 @handle 或画师 id" />
      <input v-model.trim="form.sourceName" class="subs-input" placeholder="展示名（可选）" />
      <select v-model="form.targetMode" class="subs-input">
        <option value="video">视频</option>
        <option value="comic">图集</option>
        <option value="post">帖子</option>
        <option value="text">文本</option>
      </select>
      <select v-model.number="form.libraryId" class="subs-input">
        <option :value="null">默认库</option>
        <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
      </select>
      <button class="subs-btn" :disabled="adding || !form.sourceId" @click="add">添加订阅</button>
    </div>

    <div v-if="loading" class="subs-loading">加载中…</div>
    <div v-else-if="!items.length" class="subs-empty">还没有订阅，先在上方添加一个吧。</div>
    <div v-else class="subs-list">
      <div v-for="s in items" :key="s.id" class="subs-row" :class="{ off: !s.enabled }">
        <div class="subs-main">
          <span class="subs-src" :class="`badge-${s.sourceType}`">{{ s.sourceType }}</span>
          <span class="subs-id">{{ s.sourceName || s.sourceId }}</span>
          <span v-if="s.sourceName" class="subs-handle">{{ s.sourceId }}</span>
        </div>
        <div class="subs-sub">
          <span>模式：{{ s.targetMode }}</span>
          <span v-if="s.lastItemAt">最近更新：{{ s.lastItemAt }}</span>
          <span v-if="s.error" class="subs-err">⚠ {{ s.error }}</span>
        </div>
        <div class="subs-ops">
          <label class="subs-toggle">
            <input type="checkbox" v-model="s.enabled" @change="toggleEnabled(s)" />
            启用
          </label>
          <button class="subs-del" @click="remove(s)">删除</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { subscriptionApi, type SubscriptionInput } from '../api'
import { libraryApi } from '../api'
import type { Subscription } from '../types'
import { useToast } from '../composables/useToast'

const { showToast } = useToast()
const items = ref<Subscription[]>([])
const libraries = ref<{ id: number; name: string }[]>([])
const loading = ref(false)
const adding = ref(false)

const form = reactive<SubscriptionInput>({
  sourceType: 'x',
  sourceId: '',
  sourceName: '',
  targetMode: 'video',
  libraryId: null,
  enabled: true,
})

async function load() {
  loading.value = true
  try {
    const res: any = await subscriptionApi.list()
    items.value = (res && res.success && Array.isArray(res.items)) ? res.items : []
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

async function loadLibraries() {
  try {
    const res: any = await libraryApi.getUserLibraries()
    const libs = res && res.success && Array.isArray(res.libraries) ? res.libraries : []
    libraries.value = libs.map((l: any) => ({ id: l.id, name: l.name }))
  } catch {
    libraries.value = []
  }
}

async function add() {
  if (!form.sourceId) return
  adding.value = true
  try {
    const res: any = await subscriptionApi.create({
      sourceType: form.sourceType,
      sourceId: form.sourceId,
      sourceName: form.sourceName || undefined,
      targetMode: form.targetMode,
      libraryId: form.libraryId,
      enabled: form.enabled,
    })
    if (res && res.success) {
      form.sourceId = ''
      form.sourceName = ''
      await load()
    } else {
      showToast((res && res.message) || '添加失败')
    }
  } catch (e: any) {
    showToast(e?.message || '添加失败')
  } finally {
    adding.value = false
  }
}

async function toggleEnabled(s: Subscription) {
  try {
    await subscriptionApi.update(s.id, { enabled: s.enabled })
  } catch {
    s.enabled = !s.enabled
    showToast('更新失败')
  }
}

async function remove(s: Subscription) {
  try {
    await subscriptionApi.remove(s.id)
    items.value = items.value.filter((x) => x.id !== s.id)
  } catch {
    showToast('删除失败')
  }
}

onMounted(() => {
  load()
  loadLibraries()
})
</script>

<style scoped>
.subs-page {
  max-width: 860px;
  margin: 0 auto;
  padding: 24px 16px;
}
.subs-title {
  font-size: 22px;
  margin: 0 0 6px;
}
.subs-hint {
  color: var(--text-muted, #9ca3af);
  margin: 0 0 18px;
  font-size: 14px;
}
.subs-add {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 20px;
}
.subs-input {
  background: var(--input-bg, #1f2937);
  border: 1px solid var(--border, #333);
  color: var(--text, #eee);
  border-radius: 8px;
  padding: 8px 10px;
  font-size: 14px;
}
.subs-btn {
  background: var(--accent, #f97316);
  border: none;
  color: #fff;
  border-radius: 8px;
  padding: 8px 16px;
  cursor: pointer;
}
.subs-btn:disabled {
  opacity: .5;
  cursor: not-allowed;
}
.subs-loading,
.subs-empty {
  color: var(--text-muted, #9ca3af);
  padding: 20px 0;
}
.subs-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.subs-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border: 1px solid var(--border, #2a2a2a);
  border-radius: 10px;
}
.subs-row.off {
  opacity: .55;
}
.subs-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
}
.subs-src {
  font-size: 11px;
  padding: 2px 6px;
  border-radius: 6px;
  background: rgba(249, 115, 22, .15);
  color: var(--accent, #f97316);
}
.subs-id {
  font-weight: 600;
}
.subs-handle {
  color: var(--text-muted, #6b7280);
  font-size: 12px;
}
.subs-sub {
  display: flex;
  gap: 12px;
  flex: 1;
  flex-wrap: wrap;
  color: var(--text-muted, #9ca3af);
  font-size: 12px;
}
.subs-err {
  color: var(--danger, #ef4444);
}
.subs-ops {
  display: flex;
  align-items: center;
  gap: 12px;
}
.subs-toggle {
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.subs-del {
  background: none;
  border: 1px solid var(--border, #444);
  color: var(--text-muted, #9ca3af);
  border-radius: 6px;
  padding: 4px 10px;
  cursor: pointer;
}
.subs-del:hover {
  color: var(--danger, #ef4444);
  border-color: var(--danger, #ef4444);
}
</style>
