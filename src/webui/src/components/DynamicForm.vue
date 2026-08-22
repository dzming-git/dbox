<script setup lang="ts">
import { ref, watch } from 'vue'

interface SettingItem {
  key: string
  label?: string
  type?: string          // switch | text | number | radio | checkbox | select
  default?: any
  options?: { value: any; label: string }[] | string[]
  required?: boolean
  description?: string
  group?: string
  placeholder?: string
  min?: number
  max?: number
  step?: number
}

const props = defineProps<{
  schema: SettingItem[]
  modelValue: Record<string, any>
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', v: Record<string, any>): void
}>()

// 本地副本，便于即时编辑
const form = ref<Record<string, any>>({ ...props.modelValue })

watch(() => props.modelValue, (v) => {
  form.value = { ...v }
}, { deep: true })

// schema 变更（切换插件）时重置
watch(() => props.schema, () => {
  form.value = { ...props.modelValue }
}, { deep: true })

function emitChange() {
  emit('update:modelValue', { ...form.value })
}

function normOptions(opts: any): { value: any; label: string }[] {
  if (!Array.isArray(opts)) return []
  return opts.map((o) => {
    if (typeof o === 'object' && o !== null && 'value' in o) return o
    return { value: o, label: String(o) }
  })
}

function onCheckboxToggle(key: string, value: any, checked: boolean) {
  const arr = Array.isArray(form.value[key]) ? [...form.value[key]] : []
  if (checked) {
    if (!arr.includes(value)) arr.push(value)
  } else {
    const i = arr.indexOf(value)
    if (i >= 0) arr.splice(i, 1)
  }
  form.value[key] = arr
  emitChange()
}

function isChecked(key: string, value: any): boolean {
  const arr = form.value[key]
  return Array.isArray(arr) && arr.includes(value)
}

// 按 group 分组的 schema
const groups = ref<{ name: string; items: SettingItem[] }[]>([])
watch(() => props.schema, (s) => {
  const map = new Map<string, SettingItem[]>()
  for (const item of (s || [])) {
    const g = item.group || '常规'
    if (!map.has(g)) map.set(g, [])
    map.get(g)!.push(item)
  }
  groups.value = Array.from(map.entries()).map(([name, items]) => ({ name, items }))
}, { immediate: true })
</script>

<template>
  <div class="dyn-form">
    <template v-if="!schema || !schema.length">
      <div class="dyn-empty">该插件暂无可配置项。</div>
    </template>

    <template v-for="grp in groups" :key="grp.name">
      <div v-if="groups.length > 1" class="dyn-group-title">{{ grp.name }}</div>
      <div
        v-for="item in grp.items"
        :key="item.key"
        class="dyn-row"
      >
        <label class="dyn-label">
          {{ item.label || item.key }}
          <span v-if="item.required" class="dyn-req">*</span>
        </label>

        <div class="dyn-control">
          <!-- 开关 -->
          <label v-if="item.type === 'switch'" class="dyn-switch">
            <input
              type="checkbox"
              :checked="!!form[item.key]"
              @change="form[item.key] = ($event.target as HTMLInputElement).checked; emitChange()"
            />
            <span class="dyn-switch-text">{{ form[item.key] ? '开' : '关' }}</span>
          </label>

          <!-- 文本 -->
          <input
            v-else-if="item.type === 'text'"
            type="text"
            v-model="form[item.key]"
            :placeholder="item.placeholder || ''"
            @input="emitChange"
          />

          <!-- 数字 -->
          <input
            v-else-if="item.type === 'number'"
            type="number"
            v-model.number="form[item.key]"
            :min="item.min"
            :max="item.max"
            :step="item.step || 1"
            :placeholder="item.placeholder || ''"
            @input="emitChange"
          />

          <!-- 单选 -->
          <div v-else-if="item.type === 'radio'" class="dyn-radio">
            <label v-for="opt in normOptions(item.options)" :key="String(opt.value)" class="dyn-radio-item">
              <input
                type="radio"
                :name="'rd_' + item.key"
                :value="opt.value"
                v-model="form[item.key]"
                @change="emitChange"
              />
              {{ opt.label }}
            </label>
          </div>

          <!-- 多选 -->
          <div v-else-if="item.type === 'checkbox'" class="dyn-checkbox">
            <label v-for="opt in normOptions(item.options)" :key="String(opt.value)" class="dyn-checkbox-item">
              <input
                type="checkbox"
                :checked="isChecked(item.key, opt.value)"
                @change="onCheckboxToggle(item.key, opt.value, ($event.target as HTMLInputElement).checked)"
              />
              {{ opt.label }}
            </label>
          </div>

          <!-- 下拉 -->
          <select
            v-else-if="item.type === 'select'"
            v-model="form[item.key]"
            @change="emitChange"
          >
            <option v-for="opt in normOptions(item.options)" :key="String(opt.value)" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>

          <!-- 未知类型回退：文本 -->
          <input v-else type="text" v-model="form[item.key]" @input="emitChange" />

          <div v-if="item.description" class="dyn-desc">{{ item.description }}</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.dyn-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.dyn-empty {
  padding: 24px;
  text-align: center;
  color: var(--text-tertiary);
  font-size: 13px;
}
.dyn-group-title {
  margin: 14px 0 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: .04em;
}
.dyn-group-title:first-child {
  margin-top: 0;
}
.dyn-row {
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 12px;
  align-items: start;
  padding: 12px 0;
  border-bottom: 1px solid var(--border-default);
}
.dyn-row:last-child {
  border-bottom: none;
}
.dyn-label {
  font-size: 13px;
  color: var(--text-secondary);
  padding-top: 7px;
}
.dyn-req {
  color: var(--danger);
  margin-left: 2px;
}
.dyn-control {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.dyn-control input[type="text"],
.dyn-control input[type="number"],
.dyn-control select {
  width: 100%;
  max-width: 420px;
  padding: 8px 10px;
  font-size: 13px;
  color: var(--text-primary);
  background: var(--bg-surface-2);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  outline: none;
  transition: border-color .15s;
}
.dyn-control input[type="text"]:focus,
.dyn-control input[type="number"]:focus,
.dyn-control select:focus {
  border-color: var(--accent);
}
.dyn-switch {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-secondary);
}
.dyn-switch input {
  width: 16px;
  height: 16px;
  accent-color: var(--accent);
}
.dyn-radio,
.dyn-checkbox {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
}
.dyn-radio-item,
.dyn-checkbox-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
}
.dyn-radio-item input,
.dyn-checkbox-item input {
  width: 15px;
  height: 15px;
  accent-color: var(--accent);
}
.dyn-desc {
  font-size: 12px;
  color: var(--text-tertiary);
  line-height: 1.5;
}

@media (max-width: 640px) {
  .dyn-row {
    grid-template-columns: 1fr;
    row-gap: 6px;
  }
  .dyn-label {
    padding-top: 0;
  }
  .dyn-control input[type="text"],
  .dyn-control input[type="number"],
  .dyn-control select {
    max-width: 100%;
  }
}
</style>
