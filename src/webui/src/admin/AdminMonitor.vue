<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { api } from '../api'
import { formatBytes, getUsageClass, formatUptime } from '../utils/adminCommon'

const monitorMetrics = ref<any>(null)
const monitorHistory = ref<any[]>([])
const monitorLoading = ref(false)
let monitorPollingTimer: number | null = null

const fetchMonitorMetrics = async () => {
  monitorLoading.value = true
  try {
    const res = await api.get('/api/system/metrics') as any
    if (res.success) {
      monitorMetrics.value = res.metrics
      if (res.metrics && monitorHistory.value.length < 60) {
        monitorHistory.value.push(res.metrics)
      }
    }
  } catch (error) {
    console.error('获取系统监控数据失败:', error)
  } finally {
    monitorLoading.value = false
  }
}

const startMonitorPolling = () => {
  stopMonitorPolling()
  fetchMonitorMetrics()
  monitorPollingTimer = window.setInterval(() => {
    fetchMonitorMetrics()
  }, 3000)
}

const stopMonitorPolling = () => {
  if (monitorPollingTimer !== null) {
    clearInterval(monitorPollingTimer)
    monitorPollingTimer = null
  }
}

onMounted(() => {
  startMonitorPolling()
})

onUnmounted(() => {
  stopMonitorPolling()
})
</script>

<template>
  <div class="tab-content">
    <div class="section-header">
      <h3>📈 系统监控</h3>
      <div class="section-actions">
        <button class="action-btn primary" @click="fetchMonitorMetrics" :disabled="monitorLoading">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
          {{ monitorLoading ? '加载中...' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 概览卡片 -->
    <div class="monitor-overview">
      <!-- CPU 卡片 -->
      <div class="monitor-card cpu-card">
        <div class="monitor-card-header">
          <span class="monitor-icon">🖥️</span>
          <span class="monitor-title">CPU 使用率</span>
        </div>
        <div class="monitor-card-body">
          <div class="monitor-value" :class="getUsageClass(monitorMetrics?.cpu?.usage_percent)">
            {{ monitorMetrics?.cpu?.usage_percent?.toFixed(1) || '0' }}%
          </div>
          <div class="monitor-bar-container">
            <div class="monitor-bar" :style="{ width: (monitorMetrics?.cpu?.usage_percent || 0) + '%' }"
                 :class="getUsageClass(monitorMetrics?.cpu?.usage_percent)"></div>
          </div>
          <div class="monitor-detail">
            <span>{{ monitorMetrics?.cpu?.count || 0 }} 核心</span>
            <span v-if="monitorMetrics?.cpu?.freq_current">
              {{ monitorMetrics?.cpu?.freq_current?.toFixed(0) }} MHz
            </span>
          </div>
          <!-- 每核心使用率 -->
          <div class="core-usage" v-if="monitorMetrics?.cpu?.per_core_usage">
            <div class="core-usage-item"
                 v-for="(usage, idx) in monitorMetrics.cpu.per_core_usage"
                 :key="idx">
              <span class="core-label">核心 {{ idx + 1 }}</span>
              <div class="monitor-bar-container small">
                <div class="monitor-bar" :style="{ width: usage + '%' }"
                     :class="getUsageClass(usage)"></div>
              </div>
              <span class="core-value">{{ usage.toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 内存卡片 -->
      <div class="monitor-card memory-card">
        <div class="monitor-card-header">
          <span class="monitor-icon">💾</span>
          <span class="monitor-title">内存使用</span>
        </div>
        <div class="monitor-card-body">
          <div class="monitor-value" :class="getUsageClass(monitorMetrics?.memory?.usage_percent)">
            {{ monitorMetrics?.memory?.usage_percent?.toFixed(1) || '0' }}%
          </div>
          <div class="monitor-bar-container">
            <div class="monitor-bar" :style="{ width: (monitorMetrics?.memory?.usage_percent || 0) + '%' }"
                 :class="getUsageClass(monitorMetrics?.memory?.usage_percent)"></div>
          </div>
          <div class="monitor-detail">
            <span>已用: {{ formatBytes(monitorMetrics?.memory?.used || 0) }}</span>
            <span>总计: {{ formatBytes(monitorMetrics?.memory?.total || 0) }}</span>
          </div>
          <div class="monitor-detail">
            <span>可用: {{ formatBytes(monitorMetrics?.memory?.available || 0) }}</span>
          </div>
        </div>
      </div>

      <!-- 磁盘卡片 -->
      <div class="monitor-card disk-card" v-for="disk in monitorMetrics?.disks" :key="disk.device">
        <div class="monitor-card-header">
          <span class="monitor-icon">💿</span>
          <span class="monitor-title">{{ disk.device || disk.mount_point }}</span>
        </div>
        <div class="monitor-card-body">
          <div class="monitor-value" :class="getUsageClass(disk.usage_percent)">
            {{ disk.usage_percent?.toFixed(1) || '0' }}%
          </div>
          <div class="monitor-bar-container">
            <div class="monitor-bar" :style="{ width: (disk.usage_percent || 0) + '%' }"
                 :class="getUsageClass(disk.usage_percent)"></div>
          </div>
          <div class="monitor-detail">
            <span>已用: {{ formatBytes(disk.used || 0) }}</span>
            <span>总计: {{ formatBytes(disk.total || 0) }}</span>
          </div>
          <div class="monitor-detail">
            <span>可用: {{ formatBytes(disk.free || 0) }}</span>
            <span class="fs-type">{{ disk.fs_type }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 运行时间 -->
    <div class="monitor-uptime" v-if="monitorMetrics?.uptime">
      <span class="uptime-label">系统运行时间:</span>
      <span class="uptime-value">{{ formatUptime(monitorMetrics.uptime) }}</span>
    </div>
  </div>
</template>
