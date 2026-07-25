<template>
  <div class="scripts-admin">
    <!-- 子页签 -->
    <div class="subtabs">
      <button :class="['subtab-btn', activeSub === 'scripts' ? 'active' : '']" @click="activeSub = 'scripts'">
        脚本中心
      </button>
      <button :class="['subtab-btn', activeSub === 'cookies' ? 'active' : '']" @click="activeSub = 'cookies'">
        Cookie 保险库
      </button>
    </div>

    <!-- 脚本中心 -->
    <section v-if="activeSub === 'scripts'" class="subpanel">
      <div class="panel-toolbar">
        <button class="action-btn primary" @click="reloadScripts">重新扫描</button>
        <span class="hint">仅管理员可启用 / 运行外部脚本。脚本产物最终移动到所选资源库并自动入库。</span>
      </div>

      <div v-if="loadingScripts" class="loading">加载中...</div>
      <div v-else-if="!scripts.length" class="empty">未发现脚本。请将脚本放到 extensions/scripts/&lt;id&gt;/ 并带 manifest.json。</div>

      <div v-else class="script-list">
        <div v-for="sc in scripts" :key="sc.id" class="script-card">
          <div class="script-head">
            <div>
              <div class="script-name">{{ sc.name }}</div>
              <div class="script-desc">{{ sc.description }}</div>
              <div v-if="sc.error" class="script-err">⚠ {{ sc.error }}</div>
              <div v-if="sc.required_cookies && sc.required_cookies.length" class="script-cookies">
                需要 Cookie：{{ sc.required_cookies.join('、') }}
              </div>
            </div>
            <div class="script-actions">
              <label class="switch">
                <input type="checkbox" :checked="sc.enabled" @change="toggleEnabled(sc)" />
                <span>{{ sc.enabled ? '已启用' : '已禁用' }}</span>
              </label>
              <button class="action-btn" :disabled="!sc.enabled" @click="selectScript(sc)">运行</button>
            </div>
          </div>

          <!-- 运行表单 -->
          <div v-if="selected && selected.id === sc.id" class="run-form">
            <div v-for="p in sc.params" :key="p.name" class="form-row">
              <label>{{ p.label || p.name }} <span v-if="p.required" class="req">*</span></label>

              <select v-if="p.type === 'library_select'" v-model="form[p.name]">
                <option value="">请选择资源库</option>
                <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
              </select>

              <select v-else-if="p.type === 'cookie_select'" v-model="form[p.name]">
                <option value="">请选择 Cookie</option>
                <option v-for="ck in filteredCookies(p)" :key="ck.id" :value="ck.id">
                  {{ ck.name }}（{{ ck.domain }}）
                </option>
              </select>

              <select v-else-if="p.type === 'enum'" v-model="form[p.name]">
                <option v-for="opt in (p.enum || [])" :key="opt" :value="opt">{{ opt }}</option>
              </select>

              <div v-else-if="p.type === 'enum_editable'" class="enum-editable">
                <input type="text" v-model="form[p.name]"
                  :list="'ed_' + selected.id + '_' + p.name" :placeholder="p.description || '选择或输入自定义值'" />
                <datalist :id="'ed_' + selected.id + '_' + p.name">
                  <option v-for="opt in (p.enum || [])" :key="opt" :value="opt"></option>
                </datalist>
              </div>

              <div v-else-if="p.type === 'multi_enum'" class="multi-enum">
                <label v-for="opt in (p.enum || [])" :key="opt" class="checkbox-inline">
                  <input type="checkbox" :value="opt" v-model="form[p.name]" /> {{ opt }}
                </label>
                <input v-if="p.allow_custom" type="text" class="custom-input" v-model="customInput[p.name]"
                  @keydown.enter.prevent="addCustomValue(p)"
                  @blur="addCustomValue(p)"
                  :placeholder="p.custom_hint || '输入自定义值后回车'" />
              </div>

              <input v-else-if="p.type === 'bool'" type="checkbox" v-model="form[p.name]" />

              <input v-else type="text" v-model="form[p.name]" :placeholder="p.description || ''" />

              <div v-if="p.description && p.type !== 'library_select' && p.type !== 'cookie_select'"
                   class="param-hint">{{ p.description }}</div>
            </div>

            <div class="run-buttons">
              <button class="action-btn primary" :disabled="running" @click="runSelected">开始运行</button>
              <button class="action-btn" v-if="running" @click="cancelRun">取消</button>
            </div>

            <!-- 进度 -->
            <div v-if="runningJob" class="job-progress">
              <div class="progress-bar">
                <div class="progress-fill" :style="{ width: runningJob.progress + '%' }"></div>
              </div>
              <div class="progress-text">
                状态：{{ jobStatusText(runningJob.status) }} · 进度：{{ runningJob.progress }}%
              </div>
              <div v-if="runningJob.error" class="job-error">{{ runningJob.error }}</div>
              <div class="job-logs">
                <div v-for="(lg, i) in runningJob.logs" :key="i" :class="['log-line', lg.level]">
                  <span class="log-ts">{{ lg.ts }}</span> {{ lg.message }}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- Cookie 保险库 -->
    <section v-if="activeSub === 'cookies'" class="subpanel">
      <div class="panel-toolbar">
        <button class="action-btn primary" @click="openCookieForm()">新增 Cookie</button>
        <span class="hint">Cookie 为网站登录凭证，加密保存，仅管理员可见。运行下载脚本时按需注入临时文件。</span>
      </div>

      <table class="data-table" v-if="cookies.length">
        <thead>
          <tr>
            <th>名称</th><th>域名</th><th>格式</th><th>更新时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ck in cookies" :key="ck.id">
            <td>{{ ck.name }}</td>
            <td>{{ ck.domain }}</td>
            <td>{{ ck.format }}</td>
            <td>{{ ck.updated_at || ck.created_at || '-' }}</td>
            <td>
              <button class="action-btn" @click="openCookieForm(ck)">编辑</button>
              <button class="action-btn danger" @click="removeCookie(ck)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无 Cookie 配置。</div>

      <!-- 表单弹窗 -->
      <div v-if="showCookieForm" class="modal-mask" @click.self="showCookieForm = false">
        <div class="modal">
          <div class="modal-title">{{ editingCookie ? '编辑 Cookie' : '新增 Cookie' }}</div>
          <div class="form-row">
            <label>名称</label>
            <input type="text" v-model="ckForm.name" placeholder="如：B站主号" />
          </div>
          <div class="form-row">
            <label>域名</label>
            <input type="text" v-model="ckForm.domain" placeholder="如：.bilibili.com" />
          </div>
          <div class="form-row">
            <label>格式</label>
            <select v-model="ckForm.format">
              <option value="netscape">Netscape cookies.txt</option>
              <option value="header">原始 Cookie 请求头</option>
            </select>
          </div>
          <div class="form-row">
            <label>内容</label>
            <textarea v-model="ckForm.value" rows="6"
              :placeholder="ckForm.format === 'header' ? 'SESSDATA=xxx; bili_jct=yyy' : 'Netscape 格式 cookies.txt 全文'"></textarea>
          </div>
          <div class="modal-actions">
            <button class="action-btn" @click="showCookieForm = false">取消</button>
            <button class="action-btn primary" @click="saveCookie">保存</button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onUnmounted, onMounted } from 'vue'
import { scriptApi, type ScriptInfo, type CookieProfile, type ScriptJob } from '../../api/script'
import { libraryApi } from '../../api'

const activeSub = ref<'scripts' | 'cookies'>('scripts')
const scripts = ref<ScriptInfo[]>([])
const loadingScripts = ref(false)
const selected = ref<ScriptInfo | null>(null)
const form = reactive<Record<string, any>>({})
const customInput = reactive<Record<string, string>>({})
const libraries = ref<{ id: number; name: string }[]>([])

const cookies = ref<CookieProfile[]>([])
const showCookieForm = ref(false)
const editingCookie = ref<CookieProfile | null>(null)
const ckForm = reactive<{ name: string; domain: string; format: string; value: string }>({
  name: '', domain: '', format: 'netscape', value: '',
})

const running = ref(false)
const runningJob = ref<ScriptJob | null>(null)
let pollTimer: any = null

function jobStatusText(s: string) {
  return { running: '运行中', success: '成功', failed: '失败', cancelled: '已取消', pending: '等待中' }[s] || s
}

async function loadScripts() {
  loadingScripts.value = true
  try {
    const res: any = await scriptApi.listScripts(true)
    scripts.value = (res.scripts || []).map((s: any) => ({ ...s, enabled: !!s.enabled }))
  } finally {
    loadingScripts.value = false
  }
}

async function loadCookies() {
  try {
    const res: any = await scriptApi.listCookies()
    cookies.value = res.cookies || []
  } catch (e) {
    cookies.value = []
  }
}

async function loadLibraries() {
  try {
    const res: any = await libraryApi.getUserLibraries()
    libraries.value = (res.data || res.libraries || res || []).filter((l: any) => l && l.id != null)
  } catch (e) {
    libraries.value = []
  }
}

function filteredCookies(p: any) {
  const filter = p.domain_filter
  if (!filter) return cookies.value
  return cookies.value.filter((c) => c.domain === filter || c.domain.endsWith(filter) || filter.endsWith(c.domain))
}

async function toggleEnabled(sc: ScriptInfo) {
  if (sc.enabled) {
    await scriptApi.disable(sc.id)
    sc.enabled = false
  } else {
    await scriptApi.enable(sc.id)
    sc.enabled = true
  }
}

async function reloadScripts() {
  await scriptApi.reload()
  await loadScripts()
}

function selectScript(sc: ScriptInfo) {
  selected.value = sc
  Object.keys(form).forEach((k) => delete form[k])
  Object.keys(customInput).forEach((k) => delete customInput[k])
  for (const p of sc.params) {
    if (p.type === 'multi_enum') {
      form[p.name] = Array.isArray(p.default) ? [...p.default] : []
    } else {
      form[p.name] = p.default !== undefined ? p.default : (p.type === 'bool' ? false : '')
    }
  }
  runningJob.value = null
}

// 多选参数：把用户手填的自定义值追加进数组（去重）
function addCustomValue(p: any) {
  const v = (customInput[p.name] || '').trim()
  if (v && Array.isArray(form[p.name]) && !form[p.name].includes(v)) {
    form[p.name].push(v)
  }
  customInput[p.name] = ''
}

async function runSelected() {
  if (!selected.value) return
  // 简单必填校验（多选要求非空数组）
  for (const p of selected.value.params) {
    if (p.required) {
      const v = form[p.name]
      if (p.type === 'multi_enum') {
        if (!Array.isArray(v) || v.length === 0) {
          alert(`请至少选择一项：${p.label || p.name}`)
          return
        }
      } else if (!v) {
        alert(`请填写：${p.label || p.name}`)
        return
      }
    }
  }
  running.value = true
  runningJob.value = null
  try {
    const res: any = await scriptApi.run(selected.value.id, { ...form })
    const jobId = res.job_id
    if (!jobId) {
      alert(res.message || '运行失败')
      running.value = false
      return
    }
    pollJob(jobId)
  } catch (e: any) {
    alert('运行失败：' + (e?.message || e))
    running.value = false
  }
}

function pollJob(jobId: string) {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    try {
      const res: any = await scriptApi.getJob(jobId)
      runningJob.value = res.job || null
      if (res.job && ['success', 'failed', 'cancelled'].includes(res.job.status)) {
        clearInterval(pollTimer)
        pollTimer = null
        running.value = false
      }
    } catch (e) {
      clearInterval(pollTimer)
      pollTimer = null
      running.value = false
    }
  }, 1000)
}

async function cancelRun() {
  if (!runningJob.value) return
  await scriptApi.cancelJob(runningJob.value.id)
}

function openCookieForm(ck?: CookieProfile) {
  editingCookie.value = ck || null
  ckForm.name = ck?.name || ''
  ckForm.domain = ck?.domain || ''
  ckForm.format = ck?.format || 'netscape'
  ckForm.value = ''
  showCookieForm.value = true
}

async function saveCookie() {
  if (!ckForm.name || !ckForm.domain || !ckForm.value) {
    alert('名称 / 域名 / 内容 必填')
    return
  }
  if (editingCookie.value) {
    await scriptApi.updateCookie(editingCookie.value.id, { ...ckForm })
  } else {
    await scriptApi.createCookie({ ...ckForm })
  }
  showCookieForm.value = false
  await loadCookies()
}

async function removeCookie(ck: CookieProfile) {
  if (!confirm(`确认删除 Cookie「${ck.name}」？`)) return
  await scriptApi.deleteCookie(ck.id)
  await loadCookies()
}

onMounted(() => {
  loadScripts()
  loadCookies()
  loadLibraries()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.scripts-admin { padding: 16px; color: var(--text-color, #e6e6e6); }
.subtabs { display: flex; gap: 8px; margin-bottom: 16px; }
.subtab-btn {
  padding: 8px 18px; border-radius: 8px; border: 1px solid var(--border-color, #333);
  background: var(--card-bg, #1c1c1c); color: var(--text-color, #e6e6e6); cursor: pointer;
}
.subtab-btn.active { background: var(--accent, #4f8cff); color: #fff; border-color: transparent; }
.panel-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.hint { color: #999; font-size: 12px; }
.loading, .empty { color: #999; padding: 20px; }
.script-list { display: flex; flex-direction: column; gap: 12px; }
.script-card {
  background: var(--card-bg, #1c1c1c); border: 1px solid var(--border-color, #333);
  border-radius: 10px; padding: 14px;
}
.script-head { display: flex; justify-content: space-between; gap: 12px; }
.script-name { font-weight: 600; font-size: 15px; }
.script-desc { color: #aaa; font-size: 13px; margin-top: 4px; }
.script-err { color: #ff8080; font-size: 12px; margin-top: 4px; }
.script-cookies { color: #ffcf80; font-size: 12px; margin-top: 4px; }
.script-actions { display: flex; align-items: center; gap: 10px; }
.switch { display: flex; align-items: center; gap: 6px; font-size: 13px; color: #aaa; cursor: pointer; }
.run-form { margin-top: 14px; border-top: 1px solid var(--border-color, #333); padding-top: 14px; }
.form-row { margin-bottom: 12px; display: flex; flex-direction: column; gap: 6px; }
.form-row > label { font-size: 13px; color: #ccc; }
.req { color: #ff8080; }
.param-hint { color: #888; font-size: 12px; }
.multi-enum { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; }
.checkbox-inline {
  display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: #ddd;
  cursor: pointer;
}
.checkbox-inline input { width: 15px; height: 15px; accent-color: var(--accent, #4f8cff); }
.custom-input {
  background: var(--input-bg, #141414); color: var(--text-color, #e6e6e6);
  border: 1px dashed var(--border-color, #333); border-radius: 8px; padding: 6px 10px;
  font-size: 13px; min-width: 180px;
}
.form-row input[type="text"], .form-row select, .form-row textarea {
  background: var(--input-bg, #141414); color: var(--text-color, #e6e6e6);
  border: 1px solid var(--border-color, #333); border-radius: 8px; padding: 8px 10px; font-size: 14px;
}
.run-buttons { display: flex; gap: 10px; margin-top: 6px; }
.action-btn {
  padding: 7px 14px; border-radius: 8px; border: 1px solid var(--border-color, #333);
  background: var(--card-bg, #1c1c1c); color: var(--text-color, #e6e6e6); cursor: pointer;
}
.action-btn.primary { background: var(--accent, #4f8cff); color: #fff; border-color: transparent; }
.action-btn.danger { color: #ff8080; }
.action-btn:disabled { opacity: .5; cursor: not-allowed; }
.job-progress { margin-top: 14px; }
.progress-bar { height: 8px; background: #2a2a2a; border-radius: 6px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent, #4f8cff); transition: width .3s; }
.progress-text { font-size: 13px; color: #ccc; margin: 8px 0; }
.job-error { color: #ff8080; font-size: 13px; }
.job-logs {
  background: #0e0e0e; border: 1px solid var(--border-color, #333); border-radius: 8px;
  padding: 10px; max-height: 240px; overflow: auto; font-family: monospace; font-size: 12px;
}
.log-line { margin-bottom: 3px; color: #cfcfcf; }
.log-line.error { color: #ff8080; }
.log-line.log { color: #9fd3ff; }
.log-ts { color: #666; }
.data-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.data-table th, .data-table td {
  text-align: left; padding: 10px; border-bottom: 1px solid var(--border-color, #333); font-size: 13px;
}
.modal-mask {
  position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal {
  background: var(--card-bg, #1c1c1c); border: 1px solid var(--border-color, #333); border-radius: 12px;
  padding: 20px; width: 480px; max-width: 92vw;
}
.modal-title { font-size: 16px; font-weight: 600; margin-bottom: 14px; }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
</style>
