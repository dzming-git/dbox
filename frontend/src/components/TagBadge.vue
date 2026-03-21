<script setup lang="ts">
import { computed } from 'vue'
import type { Tag } from '../types'

const props = defineProps<{
  tag: Tag
  level?: number
  active?: boolean
}>()

const emit = defineEmits<{
  click: [tag: Tag]
}>()

// 标签级别样式
const levelClass = computed(() => {
  const level = props.level || 1
  return `tag-level-${level}`
})

// 点击处理
const handleClick = () => {
  emit('click', props.tag)
}

// 格式化数量
const formatCount = (count: number): string => {
  if (count >= 1000) {
    return `${(count / 1000).toFixed(1)}k`
  }
  return String(count)
}
</script>

<template>
  <button 
    class="tag"
    :class="[levelClass, { active }]"
    @click="handleClick"
  >
    <span class="tag-name">{{ tag.name }}</span>
    <span class="tag-count" v-if="tag.video_count > 0">
      {{ formatCount(tag.video_count) }}
    </span>
  </button>
</template>

<style scoped>
.tag {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: none;
  cursor: pointer;
  transition: all 0.2s ease;
  font-family: inherit;
}

/* 一级标签 */
.tag-level-1 {
  padding: 8px 12px;
  font-size: 16px;
  font-weight: 600;
  background: #E3F2FD;
  color: #1976D2;
  border-radius: 8px;
  margin-right: 8px;
  margin-bottom: 8px;
}

.tag-level-1:hover {
  background: #BBDEFB;
}

/* 二级标签 */
.tag-level-2 {
  padding: 6px 10px;
  font-size: 14px;
  background: #F5F5F5;
  color: #424242;
  border-radius: 6px;
  margin-right: 6px;
  margin-bottom: 6px;
}

.tag-level-2:hover {
  background: #E0E0E0;
}

/* 三级标签 */
.tag-level-3 {
  padding: 4px 8px;
  font-size: 12px;
  background: #FAFAFA;
  color: #757575;
  border-radius: 4px;
  margin-right: 4px;
  margin-bottom: 4px;
}

.tag-level-3:hover {
  background: #F5F5F5;
}

/* 激活状态 */
.tag.active {
  transform: scale(1.05);
}

.tag-level-1.active {
  background: #1976D2;
  color: white;
}

.tag-level-2.active {
  background: #424242;
  color: white;
}

.tag-level-3.active {
  background: #757575;
  color: white;
}

/* 数量角标 */
.tag-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 20px;
  height: 20px;
  padding: 0 4px;
  font-size: 12px;
  font-weight: 500;
  background: rgba(0, 0, 0, 0.1);
  border-radius: 10px;
}

.tag.active .tag-count {
  background: rgba(255, 255, 255, 0.2);
}
</style>
