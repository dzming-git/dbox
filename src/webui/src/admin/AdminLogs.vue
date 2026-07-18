<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { logApi } from '../api'
import { useToast } from '../composables/useToast'

const { showToast } = useToast()

const logEntries = ref<any[]>([])
const logPage = ref(1)
const logLimit = ref(20)
const logTotal = ref(0)
const logTotalPages = ref(0)
const logType = ref('maintenance')
const logService = ref('')
const logServices = ref<string[]>([])
const logLoading = ref(false)

const logTypes = [
  { value: 'maintenance', label: '维护日志', icon: '🔧' },
  { value: 'runtime', label: '运行日志', icon: '📋' },
  { value: 'debug', label: '调试日志', icon: '🐛' },
  { value: 'operation', label: '操作日志', icon: '👤' }
]

const logLimitOptions = [10, 20, 50, 100]

const fetchLogs = async (resetPage = true) => {
  logLoading.value = true
  try {
    const params: any = { type: logType.value }
    if (resetPage) {
      logPage.value = 1
    }
    params.page = logPage.value
    params.limit = logLimit.value
    if (logService.value) {
      params.service = logService.value
    }
    const res = await logApi.getLogs(params) as any
    if (res.success) {
      logEntries.value = res.logs || []
      logTotal.value = res.total || 0
      logTotalPages.value = res.total_pages || 0
      if (res.services) {
        logServices.value = res.services
      }
    }
  } catch (error) {
    console.error('获取日志失败:', error)
    showToast('获取日志失败')
  } finally {
    logLoading.value = false
  }
}

const switchLogType = (type: string) => {
  logType.value = type
  logService.value = ''
  fetchLogs(true)
}

const switchLogService = (service: string) => {
  logService.value = service
  fetchLogs(true)
}

const changeLogPage = (page: number) => {
  logPage.value = page
  fetchLogs(false)
}

const changeLogLimit = () => {
  fetchLogs(true)
}

onMounted(() => {
  fetchLogs()
})
</script>

<template>
  <div class="tab-content">
    <div class="section-header">
      <h3>📜 系统日志</h3>
      <div class="section-actions">
        <select v-model="logLimit" @change="changeLogLimit" class="page-size-select">
          <option v-for="n in logLimitOptions" :key="n" :value="n">{{ n }} 条/页</option>
        </select>
        <button class="action-btn primary" @click="fetchLogs(true)" :disabled="logLoading">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>
          {{ logLoading ? '加载中...' : '刷新' }}
        </button>
      </div>
    </div>

    <!-- 日志类型子标签 -->
    <div class="log-type-tabs">
      <button
        v-for="lt in logTypes"
        :key="lt.value"
        class="log-type-btn"
        :class="{ active: logType === lt.value }"
        @click="switchLogType(lt.value)"
      >
        {{ lt.icon }} {{ lt.label }}
      </button>
    </div>

    <!-- 服务筛选 -->
    <div class="log-service-filter" v-if="logServices.length > 0">
      <span class="filter-label">服务筛选:</span>
      <select v-model="logService" @change="switchLogService(logService)" class="service-select">
        <option value="">全部服务</option>
        <option v-for="svc in logServices" :key="svc" :value="svc">{{ svc }}</option>
      </select>
    </div>

    <!-- 日志表格 -->
    <div class="log-container">
      <div v-if="logLoading" class="loading-text">加载中...</div>
      <div v-else-if="logEntries.length === 0" class="empty-text">暂无日志</div>
      <template v-else>
        <!-- 桌面端表格 -->
        <div class="log-table-wrapper">
          <table class="log-table">
            <thead>
              <tr>
                <th class="log-col-time">时间</th>
                <th class="log-col-level">{{ logType === 'operation' ? '来源' : '等级' }}</th>
                <th class="log-col-module">服务</th>
                <th class="log-col-content">内容</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(entry, idx) in logEntries" :key="idx">
                <td class="log-col-time log-mono">{{ entry.timestamp }}</td>
                <td class="log-col-level">
                  <span v-if="logType === 'operation'" class="log-source">{{ entry.source }}</span>
                  <span v-else class="log-badge" :class="'log-level-' + entry.level.toLowerCase()">
                    {{ entry.level }}
                  </span>
                </td>
                <td class="log-col-module log-mono">{{ entry.service }}</td>
                <td class="log-col-content">{{ entry.content }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 移动端卡片 -->
        <div class="log-cards">
          <div v-for="(entry, idx) in logEntries" :key="idx" class="log-card">
            <div class="log-card-header">
              <span v-if="logType === 'operation'" class="log-source">{{ entry.source }}</span>
              <span v-else class="log-badge" :class="'log-level-' + entry.level.toLowerCase()">
                {{ entry.level }}
              </span>
              <span class="log-card-module log-mono">{{ entry.service }}</span>
            </div>
            <div class="log-card-content">{{ entry.content }}</div>
            <div class="log-card-time log-mono">{{ entry.timestamp }}</div>
          </div>
        </div>

        <!-- 分页 -->
        <div class="log-pagination" v-if="logTotalPages > 1">
          <span class="log-page-info">共 {{ logTotal }} 条</span>
          <div class="log-page-btns">
            <button class="page-btn" :disabled="logPage <= 1" @click="changeLogPage(1)">首页</button>
            <button class="page-btn" :disabled="logPage <= 1" @click="changeLogPage(logPage - 1)">上一页</button>
            <span class="page-current">{{ logPage }} / {{ logTotalPages }}</span>
            <button class="page-btn" :disabled="logPage >= logTotalPages" @click="changeLogPage(logPage + 1)">下一页</button>
            <button class="page-btn" :disabled="logPage >= logTotalPages" @click="changeLogPage(logTotalPages)">末页</button>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>
