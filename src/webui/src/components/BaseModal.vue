<script setup lang="ts">
import { computed, watch, onBeforeUnmount, useAttrs } from 'vue'

defineOptions({ inheritAttrs: false })
const attrs = useAttrs()

/**
 * 通用弹窗组件（全项目统一接口，语义对齐 Ant Design / Element Plus / Naive UI）
 *
 * 能力：
 * 1. Teleport 到 body，彻底脱离祖先 transform/stacking context，居中永远稳定。
 * 2. 自适应尺寸：内容少自然缩小，多则不超过 max-width / max-height，超出 body 内部滚动。
 * 3. 点击框外 / ESC 关闭（closeOnMask / closeOnEsc 可关）。
 * 4. beforeClose：关闭前拦截（返回 Promise<boolean> 或 boolean），用于「内容未保存」二次确认。
 * 5. 打开时锁定 body 背景滚动，关闭时解锁（closeOnMask 等行为与滚动锁联动）。
 * 6. destroyOnClose：默认 false（关闭不销毁 DOM，组件内部状态保留）；业务表单内容由
 *    父组件在 @open / 取消回调里决定重置或回填（社区主流：组件管结构，业务管数据）。
 */
const props = withDefaults(defineProps<{
  visible: boolean
  title?: string
  /** 标题下方的副标题/描述（可选） */
  subtitle?: string
  /** 内容区最大宽度 */
  maxWidth?: string
  /** 内容区最大高度 */
  maxHeight?: string
  /** 点击遮罩是否触发关闭（默认 true） */
  closeOnMask?: boolean
  /** ESC 是否触发关闭（默认 true） */
  closeOnEsc?: boolean
  /** 是否显示右上角关闭按钮（默认 true） */
  showClose?: boolean
  /** 关闭后是否销毁 DOM（默认 false，保留组件内部状态） */
  destroyOnClose?: boolean
  /** 关闭前拦截钩子：返回 false 或 Promise<false> 则阻止关闭（用于二次确认） */
  beforeClose?: () => boolean | Promise<boolean>
}>(), {
  maxWidth: '560px',
  maxHeight: 'calc(100vh - 48px)',
  closeOnMask: true,
  closeOnEsc: true,
  showClose: true,
  destroyOnClose: false
})

const emit = defineEmits<{
  'update:visible': [boolean]
  close: []
  open: []
}>()

// 关闭入口统一走这里：先过 beforeClose 拦截，再真正关闭
let closing = false
async function requestClose() {
  if (closing) return
  if (props.beforeClose) {
    try {
      const ok = await props.beforeClose()
      if (ok === false) return
    } catch (e) {
      // beforeClose 抛异常按允许关闭处理，避免卡死弹窗
    }
  }
  closing = true
  emit('update:visible', false)
  emit('close')
  // 下一次打开前重置标记
  setTimeout(() => { closing = false }, 0)
}

function onMaskClick() {
  if (props.closeOnMask) requestClose()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.closeOnEsc) requestClose()
}

const style = computed(() => ({
  maxWidth: props.maxWidth,
  maxHeight: props.maxHeight
}))

// 打开时锁定 body 背景滚动，关闭时解锁（内聚进组件，替代原先散落各页面的滚动锁逻辑）
watch(
  () => props.visible,
  (v) => {
    if (v) {
      document.body.style.overflow = 'hidden'
      emit('open')
    } else {
      document.body.style.overflow = ''
    }
  }
)

onBeforeUnmount(() => {
  document.body.style.overflow = ''
})
</script>

<template>
  <Teleport to="body">
    <!-- 遮罩 -->
    <div v-show="visible" class="bm-overlay" @click="onMaskClick"></div>
    <!-- 弹窗主体：v-show 保留 DOM（缓存），destroyOnClose 时用 v-if -->
    <div
      v-if="!destroyOnClose"
      v-show="visible"
      class="bm-modal"
      :style="style"
      tabindex="-1"
      v-bind="attrs"
      @keydown="onKeydown"
    >
      <div v-if="title || showClose" class="bm-head">
        <div class="bm-head-text">
          <span class="bm-title">{{ title }}</span>
          <span v-if="subtitle" class="bm-subtitle">{{ subtitle }}</span>
        </div>
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
      tabindex="-1"
      v-bind="attrs"
      @keydown="onKeydown"
    >
      <div v-if="title || showClose" class="bm-head">
        <div class="bm-head-text">
          <span class="bm-title">{{ title }}</span>
          <span v-if="subtitle" class="bm-subtitle">{{ subtitle }}</span>
        </div>
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
  outline: none;
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
.bm-head-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.bm-subtitle {
  font-size: 12px;
  color: var(--text-secondary, #aaa);
  line-height: 1.4;
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
