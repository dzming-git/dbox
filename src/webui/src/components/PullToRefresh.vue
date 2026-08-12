<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { usePullToRefresh, PTR_THRESHOLD, PTR_MAX_PULL } from '../composables/usePullToRefresh'

const { state, trigger } = usePullToRefresh()

const pulling = ref(false)
const startY = ref(0)

// 顶部指示器文案与图标状态
const indicatorClass = computed(() => ({
  'ptr-indicator': true,
  'is-pull': state.phase === 'pull',
  'is-ready': state.phase === 'ready',
  'is-refreshing': state.phase === 'refreshing',
}))
const indicatorText = computed(() => {
  if (state.phase === 'refreshing') return state.mode === 'shuffle' ? '换一批中…' : '刷新中…'
  if (state.phase === 'ready') return '释放刷新'
  return '下拉刷新'
})
const arrowStyle = computed(() => ({
  transform: `rotate(${state.phase === 'ready' || state.phase === 'refreshing' ? 180 : 0}deg)`,
}))

// 内容容器随下拉平移，露出顶部指示器（iOS 风格）
const contentStyle = computed(() => {
  if (state.phase === 'idle' || state.phase === 'refreshing') {
    return { transform: 'translateY(0)', transition: 'transform 0.3s ease' }
  }
  return { transform: `translateY(${state.distance}px)`, transition: 'none' }
})

function onTouchStart(e: TouchEvent) {
  if (!state.enabled) return
  if (window.scrollY > 0) {
    pulling.value = false
    return
  }
  startY.value = e.touches[0].clientY
  pulling.value = true
}

function onTouchMove(e: TouchEvent) {
  if (!pulling.value || !state.enabled) return
  // 下拉过程中若页面已离开顶部（例如内容在手势中滚动），放弃本次下拉
  if (window.scrollY > 0) {
    pulling.value = false
    state.phase = 'idle'
    state.distance = 0
    return
  }
  const dy = e.touches[0].clientY - startY.value
  if (dy <= 0) {
    // 向上滑（收起/正常滚动），不拦截
    state.phase = 'idle'
    state.distance = 0
    return
  }
  // 阻止浏览器原生回弹，制造下拉空间
  if (e.cancelable) e.preventDefault()
  const resisted = Math.min(PTR_MAX_PULL, dy * 0.5)
  state.distance = resisted
  state.phase = resisted >= PTR_THRESHOLD ? 'ready' : 'pull'
}

function onTouchEnd() {
  if (!pulling.value) return
  pulling.value = false
  if (state.phase === 'ready') {
    trigger()
  } else {
    state.phase = 'idle'
    state.distance = 0
  }
}

onMounted(() => {
  window.addEventListener('touchstart', onTouchStart, { passive: true })
  window.addEventListener('touchmove', onTouchMove, { passive: false })
  window.addEventListener('touchend', onTouchEnd)
  window.addEventListener('touchcancel', onTouchEnd)
})

onUnmounted(() => {
  window.removeEventListener('touchstart', onTouchStart)
  window.removeEventListener('touchmove', onTouchMove)
  window.removeEventListener('touchend', onTouchEnd)
  window.removeEventListener('touchcancel', onTouchEnd)
})
</script>

<template>
  <div class="ptr-root">
    <div :class="indicatorClass">
      <span class="ptr-arrow" :style="arrowStyle">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4">
          <path d="M12 19V5" />
          <path d="M5 12l7-7 7 7" />
        </svg>
      </span>
      <span class="ptr-spinner" aria-hidden="true"></span>
      <span class="ptr-text">{{ indicatorText }}</span>
    </div>
    <div class="ptr-content" :style="contentStyle">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.ptr-root {
  position: relative;
  min-height: 100%;
}

/* 顶部指示器：默认藏在内容上方，下拉时随内容下沉而露出。
   .ptr-root 已位于固定导航之下（main-content 的 padding-top），故 top:0 即内容顶部。 */
.ptr-indicator {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-tertiary);
  opacity: 0;
  transform: translateY(-12px);
  transition: opacity 0.2s ease, transform 0.2s ease;
  pointer-events: none;
  z-index: 50;
}
.ptr-indicator.is-pull,
.ptr-indicator.is-ready,
.ptr-indicator.is-refreshing {
  opacity: 1;
  transform: translateY(0);
}

.ptr-arrow {
  display: inline-flex;
  transition: transform 0.2s ease;
}
.ptr-indicator.is-ready .ptr-arrow {
  color: var(--accent);
}

/* 刷新中隐藏箭头、显示转圈 */
.ptr-spinner {
  display: none;
  width: 16px;
  height: 16px;
  border: 2px solid var(--border-strong);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: ptr-spin 0.7s linear infinite;
}
.ptr-indicator.is-refreshing .ptr-arrow {
  display: none;
}
.ptr-indicator.is-refreshing .ptr-spinner {
  display: inline-block;
}

@keyframes ptr-spin {
  to {
    transform: rotate(360deg);
  }
}

.ptr-content {
  will-change: transform;
}
</style>
