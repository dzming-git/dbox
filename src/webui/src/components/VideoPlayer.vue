<script setup lang="ts">
import { ref, onBeforeUnmount } from 'vue'

const props = withDefaults(
  defineProps<{
    src: string
    poster?: string
    controls?: boolean
    autoplay?: boolean
  }>(),
  { controls: true, autoplay: false }
)

const player = ref<HTMLVideoElement | null>(null)
const isFullscreen = ref(false)

function toggleFullscreen() {
  const el = player.value
  if (!el) return
  if (document.fullscreenElement) {
    document.exitFullscreen().catch(() => {})
  } else {
    el.requestFullscreen?.().catch(() => {})
  }
}

function onFsChange() {
  isFullscreen.value = !!document.fullscreenElement
}
document.addEventListener('fullscreenchange', onFsChange)
onBeforeUnmount(() => {
  document.removeEventListener('fullscreenchange', onFsChange)
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {})
})
</script>

<template>
  <div class="video-player" :class="{ 'is-fullscreen': isFullscreen }">
    <video
      ref="player"
      :src="src"
      :poster="poster"
      :controls="controls"
      :autoplay="autoplay"
      class="video-el"
      playsinline
      webkit-playsinline
      x5-playsinline
      x5-video-player-type="h5-page"
      preload="metadata"
      @dblclick="toggleFullscreen"
    ></video>
    <button v-if="!controls" class="vp-fs" title="全屏" @click="toggleFullscreen">⛶</button>
  </div>
</template>

<style scoped>
.video-player {
  position: relative;
  width: 100%;
  background: #000;
  border-radius: 10px;
  overflow: hidden;
}
.video-el {
  display: block;
  width: 100%;
  max-height: 80vh;
  background: #000;
}
.video-player.is-fullscreen .video-el {
  max-height: 100vh;
}
.vp-fs {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 36px;
  height: 36px;
  border: none;
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.45);
  color: #fff;
  font-size: 18px;
  cursor: pointer;
}
.vp-fs:hover {
  background: rgba(0, 0, 0, 0.7);
}
</style>
