<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useVideoStore } from '../stores/videoStore'
import { useUserStore } from '../stores/userStore'
import {
  DEFAULT_SETTINGS,
  SETTING_KEYS,
  getEffectiveSettings,
  getSettingSource,
  getUserSettings,
  getGlobalSettings,
  loadBrowserSettings,
  saveBrowserSettings,
  resetBrowserSettings,
  saveUserSettings,
  saveGlobalSettings,
  fetchServerSettings,
  getIsAdmin,
  type SettingsData,
  type SettingScope,
} from '../utils/settings'
import { interactionApi } from '../api'
import { systemApi } from '../api/index'

const videoStore = useVideoStore()
const userStore = useUserStore()

type FieldType = 'toggle' | 'select' | 'radio'

interface FieldDef {
  key: keyof SettingsData
  label: string
  desc: string
  type: FieldType
  options?: { v: string; t: string }[]
  showIf?: keyof SettingsData
  testid?: string
}

const fields: FieldDef[] = [
  { key: 'autoplay', label: '自动播放', desc: '打开视频时自动开始播放', type: 'toggle', testid: 'autoplay-toggle' },
  {
    key: 'defaultQuality', label: '默认画质', desc: '选择视频默认播放画质', type: 'select', testid: 'default-quality-select',
    options: [
      { v: 'auto', t: '自动' }, { v: '1080p', t: '1080p' }, { v: '720p', t: '720p' },
      { v: '480p', t: '480p' }, { v: '360p', t: '360p' },
    ],
  },
  {
    key: 'subtitleLanguage', label: '字幕语言', desc: '选择默认字幕语言', type: 'select', testid: 'subtitle-language-select',
    options: [
      { v: 'off', t: '关闭' }, { v: 'zh', t: '中文' }, { v: 'en', t: 'English' },
      { v: 'ja', t: '日本語' }, { v: 'ko', t: '한국어' },
    ],
  },
  {
    key: 'theme', label: '主题', desc: '选择界面主题颜色', type: 'radio', testid: 'theme-dark-radio',
    options: [{ v: 'dark', t: '深色' }, { v: 'light', t: '浅色' }],
  },
  {
    key: 'language', label: '界面语言', desc: '选择界面显示语言', type: 'select', testid: 'interface-language-select',
    options: [
      { v: 'zh-CN', t: '简体中文' }, { v: 'zh-TW', t: '繁體中文' },
      { v: 'en-US', t: 'English' }, { v: 'ja-JP', t: '日本語' },
    ],
  },
  { key: 'blockDisliked', label: '屏蔽不喜欢的视频', desc: '开启后，标记为"不喜欢"的视频不会出现在列表中', type: 'toggle', testid: 'block-disliked-toggle' },
  {
    key: 'defaultSort', label: '默认排序方式', desc: '视频 / 图集列表首页的默认排序，未单独指定时生效', type: 'select', testid: 'default-sort-select',
    options: [
      { v: 'recommended', t: '推荐' }, { v: 'name', t: '名称' }, { v: 'created_at', t: '文件时间' },
    ],
  },
  {
    key: 'defaultOrder', label: '默认排序顺序', desc: '与排序方式搭配', type: 'select', testid: 'default-order-select',
    options: [{ v: 'desc', t: '倒序' }, { v: 'asc', t: '正序' }],
  },
  { key: 'enableNotifications', label: '启用通知', desc: '接收应用内通知', type: 'toggle' },
  { key: 'notifyOnNewVideos', label: '新视频提醒', desc: '有新视频时通知我', type: 'toggle', showIf: 'enableNotifications' },
  { key: 'autoContinue', label: '自动续播', desc: '视频播放结束后，自动跳转至合集下一集或推荐视频', type: 'toggle', testid: 'auto-continue-toggle' },
]

const tabs: { scope: SettingScope; label: string; desc: string }[] = [
  { scope: 'user', label: '我的设置', desc: '跟随你的账号，在所有设备上生效' },
  { scope: 'browser', label: '此浏览器', desc: '仅保存在当前浏览器（本机），优先级最高，覆盖其他层' },
  { scope: 'global', label: '全局默认', desc: '由管理员设置，作为全站默认；普通用户只读' },
]

const activeTab = ref<SettingScope>('user')
const form = ref<SettingsData>({ ...DEFAULT_SETTINGS })
const baseline = ref<SettingsData>({ ...DEFAULT_SETTINGS })
const loading = ref(false)
const saved = ref(false)

const isAdmin = computed(() => getIsAdmin())
const tabDef = computed(() => tabs.find((t) => t.scope === activeTab.value)!)
// 全局层：仅管理员可写
const tabReadOnly = computed(() => activeTab.value === 'global' && !isAdmin.value)
// 用户层：未登录不可编辑
const userEditable = computed(() => userStore.isLoggedIn)

function sourceLabel(key: string): string {
  const s = getSettingSource(key)
  return s === 'browser' ? '此浏览器' : s === 'user' ? '我的账号' : s === 'global' ? '全局' : '系统默认'
}

function layerRaw(scope: SettingScope): Partial<SettingsData> {
  if (scope === 'user') return getUserSettings()
  if (scope === 'global') return getGlobalSettings()
  return loadBrowserSettings()
}

function loadTab(scope: SettingScope) {
  const data = layerRaw(scope)
  form.value = { ...DEFAULT_SETTINGS, ...data } as SettingsData
  baseline.value = { ...form.value }
}

function switchTab(scope: SettingScope) {
  if (scope === 'user' && !userStore.isLoggedIn) {
    showToast('请先登录后再设置「我的设置」')
    return
  }
  activeTab.value = scope
  loadTab(scope)
}

const isDirty = computed(() =>
  SETTING_KEYS.some((k) => (form.value as Record<string, unknown>)[k] !== (baseline.value as Record<string, unknown>)[k])
)

function applyTheme() {
  document.body.className = form.value.theme === 'dark' ? 'dark-theme' : 'light-theme'
}

async function saveSettings() {
  if (tabReadOnly.value || (activeTab.value === 'user' && !userEditable.value)) return
  loading.value = true
  const scope = activeTab.value
  const original = layerRaw(scope)
  const settings: Record<string, unknown> = {}
  const reset: string[] = []
  const def = DEFAULT_SETTINGS as Record<string, unknown>
  for (const k of SETTING_KEYS) {
    const origVal = k in original ? (original as Record<string, unknown>)[k] : def[k]
    const cur = (form.value as Record<string, unknown>)[k]
    if (cur !== origVal) {
      if (k in original && cur === def[k]) reset.push(k)
      else settings[k] = cur
    }
  }

  const prevBlock = (baseline.value as Record<string, unknown>).blockDisliked

  if (scope === 'browser') {
    saveBrowserSettings(settings as Partial<SettingsData>)
    if (reset.length) resetBrowserSettings(reset)
  } else if (scope === 'user') {
    await saveUserSettings(settings as Partial<SettingsData>, reset)
  } else {
    await saveGlobalSettings(settings as Partial<SettingsData>, reset)
  }

  // 重新加载基线，刷新来源徽章
  loadTab(scope)
  applyTheme()
  if (prevBlock !== (form.value as Record<string, unknown>).blockDisliked) {
    videoStore.fetchVideos(true).catch(() => {})
  }

  setTimeout(() => {
    loading.value = false
    saved.value = true
    setTimeout(() => (saved.value = false), 2000)
  }, 400)
}

async function resetLayer() {
  const scope = activeTab.value
  if (scope === 'browser') {
    resetBrowserSettings()
  } else if (scope === 'user') {
    await saveUserSettings({}, SETTING_KEYS as string[])
  } else {
    await saveGlobalSettings({}, SETTING_KEYS as string[])
  }
  loadTab(scope)
  applyTheme()
  showToast('已重置本层设置，回落到下一层')
}

// 清除所有互动数据（账号级，后端为唯一数据源）
async function clearAllData() {
  if (confirm('确定要清除所有互动数据吗？这将删除您的收藏、点赞、踩、观看历史和稍后再看（账号云端数据，不可恢复）。')) {
    try {
      await interactionApi.clearAll()
    } catch (e) {
      console.error('清空互动数据失败:', e)
    }
    // 同时清理浏览器本地缓存（播放设置等）
    localStorage.removeItem('dplayer_browser_settings')
    showToast('所有互动数据已清除')
    loadTab(activeTab.value)
  }
}

// ============ 系统控制：电脑关机（仅管理员） ============
const shutdownMinutes = ref(0)
const shutdownLoading = ref(false)

async function doShutdown(action: 'immediate' | 'scheduled' | 'after_tasks') {
  const label: Record<string, string> = {
    immediate: '立即关机',
    scheduled: '定时关机',
    after_tasks: '任务结束后关机',
  }
  if (action === 'scheduled') {
    if (!shutdownMinutes.value || shutdownMinutes.value <= 0) {
      showToast('请先输入有效的分钟数')
      return
    }
    if (!confirm(`确定要在 ${shutdownMinutes.value} 分钟后关机吗？`)) return
  } else if (!confirm(`确定要${label[action]}吗？`)) {
    return
  }
  shutdownLoading.value = true
  try {
    await systemApi.shutdown(action, action === 'scheduled' ? shutdownMinutes.value : undefined)
    showToast(action === 'after_tasks' ? '已安排：任务结束(空闲)后自动关机' : `${label[action]}指令已发送`)
  } catch (e: any) {
    showToast('操作失败：' + (e?.response?.data?.message || e?.message || e))
  } finally {
    shutdownLoading.value = false
  }
}

async function doCancelShutdown() {
  if (!confirm('确定要取消已安排的关机计划吗？')) return
  try {
    await systemApi.cancelShutdown()
    showToast('已取消关机计划')
  } catch (e: any) {
    showToast('取消失败：' + (e?.response?.data?.message || e?.message || e))
  }
}

const toastMessage = ref('')
const showToastFlag = ref(false)
function showToast(message: string) {
  toastMessage.value = message
  showToastFlag.value = true
  setTimeout(() => (showToastFlag.value = false), 2000)
}

onMounted(async () => {
  await fetchServerSettings()
  if (!userStore.isLoggedIn) activeTab.value = 'browser'
  loadTab(activeTab.value)
})

watch(
  () => userStore.isLoggedIn,
  () => {
    if (!userStore.isLoggedIn && activeTab.value === 'user') {
      activeTab.value = 'browser'
      loadTab('browser')
    }
  }
)
</script>

<template>
  <div class="settings-page">
    <div class="page-header">
      <h1 class="page-title">设置</h1>
      <p class="page-sub">设置分为三层，优先级从高到低：此浏览器 &gt; 我的设置 &gt; 全局默认 &gt; 系统默认。上层未设置的项会自动继承下层。</p>
    </div>

    <!-- 三层切换 -->
    <div class="tab-bar">
      <button
        v-for="t in tabs"
        :key="t.scope"
        class="tab-btn"
        :class="{ active: activeTab === t.scope, locked: t.scope === 'user' && !userStore.isLoggedIn }"
        @click="switchTab(t.scope)"
      >
        {{ t.label }}
      </button>
    </div>

    <div class="tab-desc">
      <span class="tab-desc-text">{{ tabDef.desc }}</span>
      <span v-if="activeTab === 'global' && !isAdmin" class="tab-desc-warn">（仅管理员可修改）</span>
      <span v-else-if="activeTab === 'user' && !userStore.isLoggedIn" class="tab-desc-warn">（请先登录）</span>
    </div>

    <div class="settings-content">
      <section class="settings-section">
        <div
          v-for="f in fields"
          :key="f.key"
          class="setting-item"
          v-show="!f.showIf || form[f.showIf]"
        >
          <div class="setting-info">
            <label class="setting-label">
              {{ f.label }}
              <span class="source-badge" :class="'src-' + getSettingSource(f.key)">
                {{ sourceLabel(f.key) }}
              </span>
            </label>
            <p class="setting-desc">{{ f.desc }}</p>
          </div>

          <div class="setting-control">
            <!-- toggle -->
            <label v-if="f.type === 'toggle'" class="toggle-switch">
              <input
                type="checkbox"
                v-model="(form as any)[f.key]"
                :disabled="tabReadOnly || (activeTab === 'user' && !userEditable)"
                :data-testid="f.testid"
              />
              <span class="toggle-slider"></span>
            </label>

            <!-- radio -->
            <div v-else-if="f.type === 'radio'" class="radio-group">
              <label
                v-for="opt in f.options"
                :key="opt.v"
                class="radio-label"
                :data-testid="f.testid"
              >
                <input
                  type="radio"
                  v-model="(form as any)[f.key]"
                  :value="opt.v"
                  :disabled="tabReadOnly || (activeTab === 'user' && !userEditable)"
                />
                <span class="radio-text">{{ opt.t }}</span>
              </label>
            </div>

            <!-- select -->
            <select
              v-else
              v-model="(form as any)[f.key]"
              class="setting-select"
              :disabled="tabReadOnly || (activeTab === 'user' && !userEditable)"
              :data-testid="f.testid"
            >
              <option v-for="opt in f.options" :key="opt.v" :value="opt.v">{{ opt.t }}</option>
            </select>
          </div>
        </div>
      </section>

      <!-- 数据管理（仅浏览器层可见，操作本地数据） -->
      <section class="settings-section">
        <h2 class="section-title">数据管理</h2>
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">清除所有本地数据</label>
            <p class="setting-desc">删除当前浏览器存储的数据，包括收藏、观看历史等</p>
          </div>
          <button class="danger-btn" @click="clearAllData" data-testid="clear-all-data-button">
            清除数据
          </button>
        </div>
      </section>

      <!-- 系统控制（仅管理员）：电脑关机 -->
      <section class="settings-section" v-if="isAdmin">
        <h2 class="section-title">系统控制 · 电脑关机</h2>
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">立即关机</label>
            <p class="setting-desc">马上关闭这台电脑（不可恢复，请谨慎）</p>
          </div>
          <button class="danger-btn" :disabled="shutdownLoading" @click="doShutdown('immediate')">立即关机</button>
        </div>
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">定时关机</label>
            <p class="setting-desc">在指定分钟数后自动关闭电脑</p>
          </div>
          <div class="shutdown-controls">
            <input type="number" min="1" class="setting-select" v-model.number="shutdownMinutes" placeholder="分钟" />
            <button class="danger-btn" :disabled="shutdownLoading" @click="doShutdown('scheduled')">定时关机</button>
          </div>
        </div>
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">任务结束后关机</label>
            <p class="setting-desc">等待转码 / 下载等任务全部结束（空闲）后自动关机</p>
          </div>
          <button class="danger-btn" :disabled="shutdownLoading" @click="doShutdown('after_tasks')">任务结束后关机</button>
        </div>
        <div class="setting-item">
          <div class="setting-info">
            <label class="setting-label">取消关机</label>
            <p class="setting-desc">取消已安排的关机计划</p>
          </div>
          <button class="reset-btn" :disabled="shutdownLoading" @click="doCancelShutdown">取消关机</button>
        </div>
      </section>

      <!-- 操作按钮 -->
      <div class="actions">
        <button class="reset-btn" @click="resetLayer" :disabled="tabReadOnly || (activeTab === 'user' && !userEditable)">
          重置本层
        </button>
        <button
          class="save-btn"
          @click="saveSettings"
          :disabled="loading || tabReadOnly || (activeTab === 'user' && !userEditable) || !isDirty"
          data-testid="save-settings-button"
        >
          {{ loading ? '保存中...' : (activeTab === 'global' ? '保存全局默认' : activeTab === 'browser' ? '保存到此浏览器' : '保存我的设置') }}
        </button>
      </div>
    </div>

    <div v-if="saved" class="toast success" data-testid="save-success">设置已保存</div>
    <div v-if="showToastFlag" class="toast">{{ toastMessage }}</div>
  </div>
</template>

<style scoped>
.settings-page {
  padding: 24px;
  max-width: 800px;
  margin: 0 auto;
  min-height: 100vh;
  background: var(--bg-surface);
  color: var(--text-on-accent);
}

.page-header {
  margin-bottom: 20px;
}

.page-title {
  font-size: 28px;
  font-weight: 600;
  margin: 0 0 8px 0;
  color: var(--text-on-accent);
}

.page-sub {
  margin: 0;
  font-size: 13px;
  color: var(--text-tertiary);
  line-height: 1.6;
}

/* Tabs */
.tab-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}

.tab-btn {
  padding: 10px 18px;
  background: var(--bg-surface);
  border: 1px solid var(--border-default);
  border-radius: 8px;
  color: var(--text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn:hover {
  background: var(--bg-surface-hover);
}

.tab-btn.active {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--text-on-accent);
}

.tab-btn.locked {
  opacity: 0.6;
}

.tab-desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 16px;
}

.tab-desc-warn {
  color: #ff9800;
}

.settings-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.settings-section {
  background: var(--bg-surface);
  border-radius: 12px;
  padding: 24px;
}

.section-title {
  font-size: 18px;
  font-weight: 600;
  margin: 0 0 20px 0;
  color: var(--text-on-accent);
}

.setting-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 0;
  border-bottom: 1px solid var(--border-default);
}

.setting-item:last-child {
  border-bottom: none;
  padding-bottom: 0;
}

.setting-info {
  flex: 1;
}

.setting-label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 500;
  color: var(--text-on-accent);
  margin-bottom: 4px;
}

.setting-desc {
  margin: 0;
  font-size: 13px;
  color: var(--text-tertiary);
}

/* 来源徽章 */
.source-badge {
  font-size: 11px;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;
  line-height: 1.4;
  white-space: nowrap;
}
.src-browser { background: rgba(33, 150, 243, 0.18); color: var(--accent); }
.src-user { background: rgba(76, 175, 80, 0.18); color: #81c784; }
.src-global { background: rgba(255, 152, 0, 0.18); color: #ffb74d; }
.src-default { background: rgba(158, 158, 158, 0.18); color: #bdbdbd; }

.setting-control {
  flex-shrink: 0;
  margin-left: 16px;
}

/* Toggle Switch */
.toggle-switch {
  position: relative;
  display: inline-block;
  width: 48px;
  height: 24px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #444;
  transition: 0.3s;
  border-radius: 24px;
}

.toggle-slider:before {
  position: absolute;
  content: "";
  height: 18px;
  width: 18px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  transition: 0.3s;
  border-radius: 50%;
}

input:checked + .toggle-slider {
  background-color: var(--accent);
}

input:checked + .toggle-slider:before {
  transform: translateX(24px);
}

input:disabled + .toggle-slider {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Select */
.setting-select {
  padding: 8px 16px;
  background: var(--bg-surface-hover);
  border: 1px solid #444;
  border-radius: 8px;
  color: var(--text-on-accent);
  font-size: 14px;
  cursor: pointer;
  min-width: 120px;
}

.setting-select:focus {
  outline: none;
  border-color: var(--accent);
}

.setting-select:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.shutdown-controls {
  display: flex;
  gap: 8px;
  align-items: center;
}

.shutdown-controls input.setting-select {
  width: 110px;
  cursor: text;
}

/* Radio Group */
.radio-group {
  display: flex;
  gap: 16px;
}

.radio-label {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  font-size: 14px;
  color: var(--text-secondary);
}

.radio-label input[type="radio"] {
  accent-color: var(--accent);
}

.radio-label input:disabled {
  cursor: not-allowed;
}

/* Buttons */
.danger-btn {
  padding: 8px 16px;
  background: transparent;
  border: 1px solid #f44336;
  border-radius: 8px;
  color: #f44336;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.danger-btn:hover {
  background: rgba(244, 67, 54, 0.1);
}

.actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding-top: 16px;
}

.reset-btn {
  padding: 12px 24px;
  background: transparent;
  border: 1px solid #444;
  border-radius: 8px;
  color: var(--text-tertiary);
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s;
}

.reset-btn:hover:not(:disabled) {
  background: #333;
  color: var(--text-on-accent);
}

.save-btn {
  padding: 12px 24px;
  background: var(--accent);
  border: none;
  border-radius: 8px;
  color: var(--text-on-accent);
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.save-btn:hover:not(:disabled) {
  background: var(--accent-active);
}

.save-btn:disabled,
.reset-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Toast */
.toast {
  position: fixed;
  bottom: 80px;
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.8);
  color: var(--text-on-accent);
  padding: 12px 24px;
  border-radius: 24px;
  font-size: 14px;
  z-index: 2000;
  animation: fadeInOut 2s ease;
}

.toast.success {
  background: #4caf50;
}

@keyframes fadeInOut {
  0% { opacity: 0; transform: translateX(-50%) translateY(20px); }
  10% { opacity: 1; transform: translateX(-50%) translateY(0); }
  90% { opacity: 1; transform: translateX(-50%) translateY(0); }
  100% { opacity: 0; transform: translateX(-50%) translateY(-20px); }
}

@media (max-width: 768px) {
  .settings-page {
    padding: 16px;
  }

  .page-title {
    font-size: 22px;
  }

  .setting-item {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }

  .setting-control {
    margin-left: 0;
  }

  .radio-group {
    flex-direction: column;
    gap: 8px;
  }

  .actions {
    flex-direction: column;
  }

  .reset-btn,
  .save-btn {
    width: 100%;
  }
}
</style>
