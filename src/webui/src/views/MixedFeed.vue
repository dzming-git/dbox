<template>
  <div class="mixed-feed">
    <div v-if="loading" class="feed-loading">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>
    <div v-else-if="items.length === 0" class="feed-empty">
      <p>暂无内容</p>
    </div>
    <div v-else class="video-grid">
      <MediaCard
        v-for="item in items"
        :key="`${item.type}-${item.hash}`"
        :item="item"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import MediaCard from '../components/MediaCard.vue'
import { fetchMixedFeed, type MediaItem } from '../utils/media'

const items = ref<MediaItem[]>([])
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    items.value = await fetchMixedFeed({ limit: 60 })
  } catch (e) {
    console.error('加载帖子失败', e)
    items.value = []
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.mixed-feed {
  padding: 16px 0;
}
.video-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}
.feed-loading,
.feed-empty {
  text-align: center;
  padding: 48px 0;
  color: #888;
}
.spinner {
  width: 32px;
  height: 32px;
  border: 3px solid rgba(255, 255, 255, 0.2);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
