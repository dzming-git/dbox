<script setup lang="ts">
import { computed } from 'vue'

/**
 * 通用弹窗组件（全项目统一接口）
 *
 * 特性：
 * 1. Teleport 到 body，彻底脱离祖先 transform/stacking context，居中永远稳定。
 * 2. 自适应尺寸：内容少时自然缩小，内容多时不超过 max-width / max-height，
 *    超出部分 body 内部滚动。
 * 3. 点击框外（遮罩）自动关闭（closeOnMask 可关）。
 * 4. 关闭后内容自动缓存：默认用 v-show 而非 v-if 销毁 DOM，
 *    再次打开时已填写内容仍在（防误触丢失）。如需每次打开都重置，
 *    传 destroyOnClose。
 * 5. 统一关闭回调：@close，以及 ESC 关闭。
 */
const props = withDefaults(defineProps<{
  visible: boolean
  title?: string
  /** 内容区最大宽度 */
  maxWidth?: string
  /** 内容区最大高度 */
  maxHeight?: string
  /** 点击遮罩是否关闭（默认 true） */
  closeOnMask?: boolean
  /** 是否显示右上角关闭按钮（默认 true） */
  showClose?: boolean
  /** 每次关闭后销毁 DOM（默认 false = 保留内容缓存） */
  destroyOnClose?: boolean
  /** 点击遮罩/关闭按钮/ESC 时是否可关闭（用于有未保存内容时的二次确认） */
  closable?: boolean
}>(), {
  maxWidth: '560px',
  maxHeight: 'calc(100vh - 48px)',
  closeOnMask: true,
  showClose: true,
  destroyOnClose: false,
  closable: true
})

const emit = defineEmits<{
  'update:visible': [boolean]
  close: []
  open: []
}>()

function requestClose() {
  if (!props.closable) return
  emit('update:visible', false)
  emit('close')
}

function onMaskClick() {
  if (props.closeOnMask) requestClose()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') requestClose()
}

const style = computed(() => ({
  maxWidth: props.maxWidth,
  maxHeight: props.maxHeight
}))
</script>

<template>
  <Teleport to="body">
    <!-- 遮罩：始终渲染，配合 v-show 控制显示 -->
    <div
      v-show="visible"
      class="bm-overlay"
      @click="onMaskClick"
    ></div>
    <!-- 弹窗主体：v-show 保持 DOM 存活以缓存内容（destroyOnClose 时用 v-if） -->
    <div
      v-if="!destroyOnClose"
      v-show="visible"
      class="bm-modal"
      :style="style"
      @keydown="onKeydown"
    >
      <div v-if="title || showClose" class="bm-head">
        <span class="bm-title">{{ title }}</span>
        <button v-if="showClose" class="bm-close" @click="requestClose">×</button>
      </div>
      <div class="bm-body">
        <slot />
      </div>
      <div v-if="$slots.footer" class="bm-foot">
        <slot name="footer" />
      </div>
    </div>
    <div
      v-else-if="visible"
      class="bm-modal"
      :style="style"
      @keydown="onKeydown"
    >
      <div v-if="title || showClose" class="bm-head">
        <span class="bm-title">{{ title }}</span>
        <button v-if="showClose" class="bm-close" @click="requestClose">×</button>
      </div>
      <div class="bm-body">
        <slot />
      </div>
      <div v-if="$slots.footer" class="bm-foot">
        <slot name="footer" />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.bm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 9500;
}
.bm-modal {
  position: fixed;
  left: 50%;
  top: 50%;
  transform: translate(-50%, -50%);
  width: calc(100% - 32px);
  background: var(--bg-elevated, #1e1e22);
  border: 1px solid var(--border-subtle, #2e2e34);
  border-radius: 14px;
  z-index: 9501;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.55);
}
.bm-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: var(--bg-surface-2, #2a2a30);
  flex-shrink: 0;
}
.bm-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-primary, #eee);
}
.bm-close {
  background: none;
  border: none;
  color: var(--text-secondary, #aaa);
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  padding: 0 2px;
}
.bm-close:hover {
  color: var(--text-primary, #eee);
}
.bm-body {
  padding: 18px;
  overflow-y: auto;
  flex: 1 1 auto;
  min-height: 0;
}
.bm-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 18px;
  border-top: 1px solid var(--border-subtle, #2e2e34);
  flex-shrink: 0;
}
</style>
