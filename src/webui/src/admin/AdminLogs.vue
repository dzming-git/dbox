<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { logApi } from '../api'

const logType = ref('maintenance')
const logService = ref('')
const logLevel = ref('')
const logUser = ref('')
const logKeyword = ref('')
const logDate = ref('')

const logServices = ref<string[]>([])   // 兼容旧字段（模块名列表）
const logModules = ref<string[]>([])     // 模块维度 facet
const logLevels = ref<string[]>([])       // 等级维度 facet
const logUsers = ref<string[]>([])        // 操作人维度 facet

const logLogs = ref<any[]>([])
const logTotal = ref(0)
const logTotalPages = ref(0)
const logPage = ref(1)
const logLimit = ref(20)
const logLoading = ref(false)

const logTypes = [
  { value: 'maintenance', label: '维护日志' },
  { value: 'runtime', label: '运行日志' },
  { value: 'debug', label: '调试日志' },
  { value: 'operation', label: '操作审计' }
]

const levelOptions = ['DEBUG', 'INFO', 'WARN', 'ERROR', 'FATAL']

const loadLogs = async () => {
  logLoading.value = true
  try {
    const params: any = { type: logType.value, page: logPage.value, limit: logLimit.value }
    if (logService.value) params.service = logService.value
    if (logLevel.value) params.level = logLevel.value
    if (logUser.value) params.user = logUser.value
    if (logKeyword.value) params.keyword = logKeyword.value
    if (logDate.value) params.date = logDate.value

    const res = await logApi.getLogs(params)
    logLogs.value = res.logs || []
    logTotal.value = res.total || 0
    logTotalPages.value = res.total_pages || 0
    // facet 列表：优先用后端返回的独立维度，回退到 services
    logModules.value = res.modules || res.services || []
    logServices.value = res.services || res.modules || []
    logLevels.value = res.levels || []
    logUsers.value = res.users || []
  } catch (e) {
    console.error('加载日志失败', e)
  } finally {
    logLoading.value = false
  }
}

const switchLogType = (type: string) => {
  logType.value = type
  // 切换类型时重置与该类型无关的维度
  logService.value = ''
  logLevel.value = ''
  logUser.value = ''
  logKeyword.value = ''
  logDate.value = ''
  logPage.value = 1
  loadLogs()
}

// 任意筛选条件变化时，回到第一页并重新加载
const onFilterChange = () => {
  logPage.value = 1
  loadLogs()
}

const changeLogPage = (page: number) => {
  logPage.value = page
  loadLogs()
}

const changeLogLimit = (e: Event) => {
  logLimit.value = Number((e.target as HTMLSelectElement).value)
  logPage.value = 1
  loadLogs()
}

const resetFilters = () => {
  logService.value = ''
  logLevel.value = ''
  logUser.value = ''
  logKeyword.value = ''
  logDate.value = ''
  logPage.value = 1
  loadLogs()
}

// 操作审计类型下等级无意义，自动隐藏等级筛选
const showLevelFilter = () => logType.value !== 'operation'
// 非操作审计类型下操作人无意义，自动隐藏用户筛选
const showUserFilter = () => logType.value === 'operation'

onMounted(loadLogs)
</script>

<template>
  <div class="admin-logs">
    <!-- 日志类型切换 -->
    <div class="log-type-tabs">
      <button
        v-for="lt in logTypes"
        :key="lt.value"
        class="log-type-btn"
        :class="{ active: logType === lt.value }"
        @click="switchLogType(lt.value)"
      >{{ lt.label }}</button>
    </div>

    <!-- 多维筛选区 -->
    <div class="log-filters">
      <!-- 关键字 -->
      <div class="filter-item filter-keyword">
        <label class="filter-label">关键字</label>
        <input
          v-model="logKeyword"
          type="text"
          class="filter-input"
          placeholder="搜索日志内容…"
          @input="onFilterChange"
        />
      </div>

      <!-- 模块 -->
      <div class="filter-item" v-if="logModules.length > 0">
        <label class="filter-label">模块</label>
        <select v-model="logService" class="filter-select" @change="onFilterChange">
          <option value="">全部模块</option>
          <option v-for="m in logModules" :key="m" :value="m">{{ m }}</option>
        </select>
      </div>

      <!-- 等级 -->
      <div class="filter-item" v-if="showLevelFilter()">
        <label class="filter-label">等级</label>
        <select v-model="logLevel" class="filter-select" @change="onFilterChange">
          <option value="">全部等级</option>
          <option v-for="lv in (logLevels.length ? logLevels : levelOptions)" :key="lv" :value="lv">{{ lv }}</option>
        </select>
      </div>

      <!-- 操作人 -->
      <div class="filter-item" v-if="showUserFilter()">
        <label class="filter-label">操作人</label>
        <input
          v-model="logUser"
          type="text"
          class="filter-input filter-user"
          placeholder="用户名 / id …"
          @input="onFilterChange"
        />
        <datalist v-if="logUsers.length" id="log-user-list">
          <option v-for="u in logUsers" :key="u" :value="u"></option>
        </datalist>
      </div>

      <!-- 日期 -->
      <div class="filter-item">
        <label class="filter-label">日期</label>
        <input
          v-model="logDate"
          type="date"
          class="filter-input filter-date"
          @change="onFilterChange"
        />
      </div>

      <button class="filter-reset-btn" @click="resetFilters">重置</button>
    </div>

    <!-- 日志表格 -->
    <div class="log-container">
      <div class="log-table-wrapper" v-if="!logLoading && logLogs.length">
        <table class="log-table">
          <thead>
            <tr>
              <th class="log-col-time">时间</th>
              <th class="log-col-level">{{ logType === 'operation' ? '来源' : '等级' }}</th>
              <th class="log-col-module">模块</th>
              <th class="log-col-content">内容</th>
              <th v-if="logType === 'operation'" class="log-col-user">操作人</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(entry, idx) in logLogs" :key="idx">
              <td class="log-col-time">{{ entry.timestamp }}</td>
              <td class="log-col-level">
                <span
                  v-if="logType === 'operation'"
                  class="log-source"
                >{{ entry.source }}</span>
                <span
                  v-else
                  class="log-badge"
                  :class="'log-level-' + (entry.level || 'info').toLowerCase()"
                >{{ entry.level }}</span>
              </td>
              <td class="log-col-module">{{ entry.service }}</td>
              <td class="log-col-content log-mono">{{ entry.content }}</td>
              <td v-if="logType === 'operation'" class="log-col-user log-mono">{{ entry.user || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 移动端卡片 -->
      <div class="log-cards" v-if="!logLoading && logLogs.length">
        <div class="log-card" v-for="(entry, idx) in logLogs" :key="idx">
          <div class="log-card-header">
            <span v-if="logType !== 'operation'" class="log-badge" :class="'log-level-' + (entry.level || 'info').toLowerCase()">{{ entry.level }}</span>
            <span v-else class="log-source">{{ entry.source }}</span>
            <span class="log-card-module">{{ entry.service }}</span>
            <span class="log-card-time">{{ entry.timestamp }}</span>
          </div>
          <div class="log-card-content log-mono">{{ entry.content }}</div>
          <div v-if="logType === 'operation' && entry.user" class="log-card-operator log-mono">操作人: {{ entry.user }}</div>
        </div>
      </div>

      <div v-if="logLoading" class="loading-text">加载中…</div>
      <div v-if="!logLoading && !logLogs.length" class="empty-text">暂无日志</div>

      <!-- 分页 -->
      <div class="log-pagination" v-if="logLogs.length">
        <div class="log-page-info">
          共 {{ logTotal }} 条 · 第 {{ logPage }} / {{ logTotalPages }} 页
        </div>
        <div class="log-page-btns">
          <button class="page-btn" :disabled="logPage <= 1" @click="changeLogPage(1)">首页</button>
          <button class="page-btn" :disabled="logPage <= 1" @click="changeLogPage(logPage - 1)">上一页</button>
          <span class="page-current">{{ logPage }} / {{ logTotalPages }}</span>
          <button class="page-btn" :disabled="logPage >= logTotalPages" @click="changeLogPage(logPage + 1)">下一页</button>
          <button class="page-btn" :disabled="logPage >= logTotalPages" @click="changeLogPage(logTotalPages)">末页</button>
          <select class="page-size-select" :value="logLimit" @change="changeLogLimit">
            <option :value="20">20/页</option>
            <option :value="50">50/页</option>
            <option :value="100">100/页</option>
          </select>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.admin-logs {
  display: flex;
  flex-direction: column;
  height: 100%;
}

/* 多维筛选区 */
.log-filters {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 16px;
  padding: 12px 14px;
  background: #1a1a24;
  border: 1px solid #2d2d3f;
  border-radius: 8px;
}

.filter-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.filter-label {
  font-size: 12px;
  color: #8b949e;
  font-weight: 500;
}

.filter-input,
.filter-select {
  padding: 6px 10px;
  border: 1px solid #2d2d3f;
  border-radius: 6px;
  background: #16161d;
  font-size: 13px;
  min-width: 160px;
  color: #e1e1e1;
}

.filter-keyword .filter-input {
  min-width: 220px;
}

.filter-select:focus,
.filter-input:focus {
  outline: none;
  border-color: #1976d2;
}

.filter-reset-btn {
  padding: 6px 16px;
  border: 1px solid #2d2d3f;
  border-radius: 6px;
  background: #23232f;
  cursor: pointer;
  font-size: 13px;
  color: #c9d1d9;
  height: 34px;
  margin-left: auto;
}

.filter-reset-btn:hover {
  background: #2a2a38;
}

/* 移动端适配 */
@media (max-width: 768px) {
  .log-filters {
    flex-direction: column;
    align-items: stretch;
  }
  .filter-item,
  .filter-keyword .filter-input,
  .filter-input,
  .filter-select {
    min-width: 0;
    width: 100%;
  }
  .filter-reset-btn {
    margin-left: 0;
  }
}
</style>
