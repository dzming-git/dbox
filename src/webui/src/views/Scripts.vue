<template>
  <div class="scripts-page">
    <header class="page-header">
      <h1 class="page-title">拓展脚本</h1>
      <p class="page-subtitle">运行外部下载 / 处理任务（如 X 媒体下载器）。仅管理员可启用与运行，脚本产物最终移动到所选资源库并自动入库。</p>
    </header>

    <!-- 子页签 -->
    <div class="subtabs">
      <button :class="['subtab-btn', activeSub === 'scripts' ? 'active' : '']" @click="activeSub = 'scripts'">
        脚本中心
      </button>
      <button :class="['subtab-btn', activeSub === 'cookies' ? 'active' : '']" @click="activeSub = 'cookies'">
        凭证保险库
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
              <button v-if="sc.ui && sc.ui.mount === 'panel'" class="action-btn" :disabled="!sc.enabled" @click="togglePanel(sc)">
                {{ panelOpenId === sc.id ? '收起面板' : '打开面板' }}
              </button>
              <button v-if="!(selected && selected.id === sc.id)" class="action-btn" :disabled="!sc.enabled" @click="selectScript(sc)">配置参数</button>
              <button v-else class="action-btn" @click="collapseScript(sc)">收起</button>
            </div>
          </div>

          <!-- 运行表单 -->
          <div v-if="selected && selected.id === sc.id" class="run-form">
            <div class="run-form-title">运行参数</div>
            <div v-for="p in sc.params" :key="p.name" class="form-row">
              <label>{{ p.label || p.name }} <span v-if="p.required" class="req">*</span>
                <span v-if="p.user_defaultable" class="defaultable-tag">可设默认</span>
              </label>

              <select v-if="p.type === 'library_select'" v-model="form[p.name]">
                <option value="">请选择资源库</option>
                <option v-for="lib in libraries" :key="lib.id" :value="lib.id">{{ lib.name }}</option>
              </select>

              <select v-else-if="p.type === 'cookie_select'" v-model="form[p.name]" style="display:none">
                <option value="">自动匹配</option>
                <option v-for="ck in filteredCookies(p)" :key="ck.id" :value="ck.id">
                  {{ ck.name }}（{{ ck.domain }}）
                </option>
              </select>
              <div v-else-if="p.type === 'cookie_select'" class="param-hint">
                系统已按域名（{{ p.domain_filter || '对应站点' }}）自动匹配凭证保险库，无需手动选择
              </div>

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
              <button class="action-btn" :disabled="running" @click="saveDefaults">保存当前值为默认</button>
            </div>
            <div v-if="defaultHint" class="default-hint">{{ defaultHint }}</div>

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
              <!-- 脚本分阶段交互 -->
              <div v-if="interaction" class="job-interaction">
                <div class="interaction-prompt">{{ interaction.prompt }}</div>
                <div v-if="interaction.options && !interaction.multi" class="interaction-options">
                  <label v-for="opt in interaction.options" :key="opt.value" class="radio-inline">
                    <input type="radio" :value="opt.value" v-model="interactionValue" /> {{ opt.label }}
                  </label>
                </div>
                <div v-else-if="interaction.options && interaction.multi" class="multi-enum">
                  <label v-for="opt in interaction.options" :key="opt.value" class="checkbox-inline">
                    <input type="checkbox" :value="opt.value" v-model="interactionValue" /> {{ opt.label }}
                  </label>
                </div>
                <div v-if="interaction.allow_text" class="form-row">
                  <label>{{ interaction.text_hint || '自定义输入' }}</label>
                  <input type="text" v-model="interactionText" :placeholder="interaction.text_hint || ''" />
                </div>
                <div class="run-buttons">
                  <button class="action-btn primary" @click="submitInteraction">提交</button>
                </div>
              </div>
            </div>
          </div>

          <!-- 内嵌 UI 面板（mount=panel 的扩展，如 X 下载预览） -->
          <div v-if="sc.ui && sc.ui.mount === 'panel' && panelOpenId === sc.id" class="script-panel">
            <iframe
              :id="`ext-panel-frame-${sc.id}`"
              class="script-panel-frame"
              :sandbox="sc.ui.sandbox"
              :srcdoc="panelHtml[sc.id] || ''"
            ></iframe>
          </div>
        </div>
      </div>
    </section>

    <!-- 凭证保险库 -->
    <section v-if="activeSub === 'cookies'" class="subpanel">
      <div class="panel-toolbar">
        <button class="action-btn primary" @click="openCookieForm()">新增凭证</button>
        <span class="hint">凭证加密保存，仅管理员可见。支持 Cookie（网站登录）、Token / API Key / 密码（单行密文），供脚本免登录调用外部服务。</span>
      </div>

      <table class="data-table" v-if="cookies.length">
        <thead>
          <tr>
            <th>类型</th><th>名称</th><th>域名</th><th>格式</th><th>更新时间</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="ck in cookies" :key="ck.id">
            <td>{{ kindLabel(ck.kind) }}</td>
            <td>{{ ck.name }}</td>
            <td>{{ ck.domain }}</td>
            <td>{{ ck.format || '-' }}</td>
            <td>{{ ck.updated_at || ck.created_at || '-' }}</td>
            <td>
              <button class="action-btn" @click="openCookieForm(ck)">编辑</button>
              <button class="action-btn danger" @click="removeCookie(ck)">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-else class="empty">暂无凭证配置。</div>

      <!-- 表单弹窗 -->
      <div v-if="showCookieForm" class="modal-mask" @click.self="showCookieForm = false">
        <div class="modal">
          <div class="modal-title">{{ editingCookie ? '编辑凭证' : '新增凭证' }}</div>
          <div class="form-row">
            <label>类型</label>
            <select v-model="ckForm.kind" :disabled="!!editingCookie">
              <option value="cookie">Cookie（网站登录）</option>
              <option value="token">Token</option>
              <option value="apikey">API Key</option>
              <option value="password">密码</option>
            </select>
          </div>
          <div class="form-row">
            <label>名称</label>
            <input type="text" v-model="ckForm.name" placeholder="如：B站主号 / codebuddy" />
          </div>
          <div class="form-row">
            <label>域名 / 用途</label>
            <input type="text" v-model="ckForm.domain" placeholder="如：.bilibili.com / codebuddy" />
          </div>
          <div class="form-row" v-if="ckForm.kind === 'cookie'">
            <label>格式</label>
            <select v-model="ckForm.format">
              <option value="netscape">Netscape cookies.txt</option>
              <option value="header">原始 Cookie 请求头</option>
              <option value="json">JSON</option>
            </select>
          </div>
          <div class="form-row">
            <label>{{ ckForm.kind === 'cookie' ? '内容' : '密文' }}</label>
            <textarea v-if="ckForm.kind === 'cookie'" v-model="ckForm.value" rows="6"
              :placeholder="ckForm.format === 'header' ? 'SESSDATA=xxx; bili_jct=yyy' : 'Netscape 格式 cookies.txt 全文'"></textarea>
            <textarea v-else v-model="ckForm.value" rows="3"
              :placeholder="ckForm.kind === 'token' ? 'Bearer / API token 全文' : (ckForm.kind === 'apikey' ? '第三方服务 API Key' : '账号口令')"></textarea>
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
import { ref, reactive, onUnmounted, onMounted, nextTick } from 'vue'
import { scriptApi, type ScriptInfo, type CookieProfile, type ScriptJob } from '../api/script'
import { libraryApi } from '../api'

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
const ckForm = reactive<{ kind: string; name: string; domain: string; format: string; value: string; note: string }>({
  kind: 'cookie', name: '', domain: '', format: 'netscape', value: '', note: '',
})

const KIND_LABELS: Record<string, string> = {
  cookie: 'Cookie',
  token: 'Token',
  apikey: 'API Key',
  password: '密码',
}
function kindLabel(kind?: string): string {
  return KIND_LABELS[kind || 'cookie'] || (kind || 'Cookie')
}

const running = ref(false)
const runningJob = ref<ScriptJob | null>(null)
const defaultHint = ref('')
let pollTimer: any = null

// 内嵌 UI 面板（mount=panel 的扩展，如 X 下载预览）
const panelOpenId = ref<string | null>(null)
const panelHtml = ref<Record<string, string>>({})
const token = ref('')

async function loadToken() {
  const raw = localStorage.getItem('token') || localStorage.getItem('access_token') || sessionStorage.getItem('token')
  token.value = raw || ''
}

async function togglePanel(sc: ScriptInfo) {
  if (panelOpenId.value === sc.id) {
    panelOpenId.value = null
    return
  }
  panelOpenId.value = sc.id
  // 每次打开都重新拉取最新 panel.html（后端 no-store + 避免 Vue 变量缓存旧版本）。
  try {
    const res: any = await scriptApi.getPanel(sc.id)
    panelHtml.value[sc.id] = res
  } catch (e) {
    panelHtml.value[sc.id] = '<p style="color:#f66;padding:12px">面板加载失败</p>'
  }
  await nextTick()
  pushPanelToken(sc.id)
}

function pushPanelToken(id: string) {
  const iframe = document.getElementById(`ext-panel-frame-${id}`) as HTMLIFrameElement | null
  if (iframe?.contentWindow) {
    iframe.contentWindow.postMessage({ type: 'DBOX_TOKEN', token: token.value }, '*')
  }
}

// 脚本分阶段交互态
const interaction = ref<any>(null)
const interactionValue = ref<any>('')
const interactionText = ref('')

function jobStatusText(s: string) {
  return {
    running: '运行中', success: '成功', failed: '失败', cancelled: '已取消',
    pending: '等待中', awaiting_input: '等待选择',
  }[s] || s
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
  defaultHint.value = ''
  // 载入当前管理员的个人默认值，覆盖 manifest 默认值
  loadDefaults(sc.id)
}

function collapseScript(sc: ScriptInfo) {
  if (selected.value && selected.value.id === sc.id) {
    selected.value = null
    runningJob.value = null
    interaction.value = null
  }
}

async function loadDefaults(scriptId: string) {
  try {
    const res: any = await scriptApi.getDefaults(scriptId)
    const d = res.defaults || {}
    for (const p of selected.value?.params || []) {
      if (p.name in d) {
        if (p.type === 'multi_enum' && !Array.isArray(d[p.name])) {
          form[p.name] = d[p.name] != null && d[p.name] !== '' ? [d[p.name]] : []
        } else {
          form[p.name] = d[p.name]
        }
      }
    }
  } catch (e) {
    // 默认值加载失败不影响正常运行
  }
}

async function saveDefaults() {
  if (!selected.value) return
  // 仅收集 manifest 标记 user_defaultable 的参数
  const defaults: Record<string, any> = {}
  for (const p of selected.value.params) {
    if (p.user_defaultable && p.name in form) {
      defaults[p.name] = form[p.name]
    }
  }
  try {
    await scriptApi.saveDefaults(selected.value.id, defaults)
    defaultHint.value = '已保存为你的默认值，下次运行将自动填入'
  } catch (e) {
    defaultHint.value = '保存默认值失败'
  }
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
      const job = res.job
      if (job) {
        // 同步交互态：进入 awaiting_input 时初始化，离开时清空（避免覆盖用户已选）
        if (job.status === 'awaiting_input' && job.pending_input) {
          if (!interaction.value || interaction.value.prompt !== job.pending_input.prompt) {
            interaction.value = job.pending_input
            interactionValue.value = job.pending_input.multi ? [] : ''
            interactionText.value = ''
          }
        } else {
          interaction.value = null
        }
        if (['success', 'failed', 'cancelled'].includes(job.status)) {
          clearInterval(pollTimer)
          pollTimer = null
          running.value = false
          interaction.value = null
        }
      }
    } catch (e) {
      clearInterval(pollTimer)
      pollTimer = null
      running.value = false
    }
  }, 1000)
}

async function submitInteraction() {
  if (!interaction.value || !runningJob.value) return
  let val: any
  if (interaction.value.multi) {
    val = Array.isArray(interactionValue.value) ? [...interactionValue.value] : []
    if (interaction.value.allow_text && interactionText.value.trim()) {
      val.push(interactionText.value.trim())
    }
    if (!val.length) {
      alert('请至少选择一项')
      return
    }
  } else if (interaction.value.allow_text && interactionText.value.trim()) {
    val = interactionText.value.trim()
  } else {
    val = interactionValue.value
    if (!val) {
      alert('请选择一项')
      return
    }
  }
  await scriptApi.respondJob(runningJob.value.id, val)
  interaction.value = null
}

async function cancelRun() {
  if (!runningJob.value) return
  await scriptApi.cancelJob(runningJob.value.id)
}

function openCookieForm(ck?: CookieProfile) {
  editingCookie.value = ck || null
  ckForm.kind = ck?.kind || 'cookie'
  ckForm.name = ck?.name || ''
  ckForm.domain = ck?.domain || ''
  ckForm.format = ck?.format || (ck?.kind === 'cookie' ? 'netscape' : 'raw')
  ckForm.value = ''
  ckForm.note = ck?.note || ''
  showCookieForm.value = true
}

async function saveCookie() {
  if (!ckForm.name || !ckForm.domain || !ckForm.value) {
    alert('名称 / 域名 / 密文 必填')
    return
  }
  const payload: Record<string, any> = {
    kind: ckForm.kind,
    name: ckForm.name,
    domain: ckForm.domain,
    value: ckForm.value,
    note: ckForm.note,
  }
  if (ckForm.kind === 'cookie') payload.format = ckForm.format
  if (editingCookie.value) {
    await scriptApi.updateCookie(editingCookie.value.id, payload)
  } else {
    await scriptApi.createCookie(payload)
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
  loadToken()
  loadScripts()
  loadCookies()
  loadLibraries()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.scripts-page { max-width: 960px; margin: 0 auto; padding: 24px 16px 48px; }
.page-header { margin-bottom: 20px; }
.page-title { font-size: 22px; font-weight: 700; color: var(--text-primary); margin: 0; }
.page-subtitle { color: var(--text-secondary); font-size: 13px; margin: 6px 0 0; }
.subtabs { display: flex; gap: 8px; margin-bottom: 16px; }
.subtab-btn {
  padding: 8px 18px; border-radius: 8px; border: 1px solid var(--border-default);
  background: var(--bg-surface); color: var(--text-primary); cursor: pointer; font-size: 14px;
}
.subtab-btn.active { background: var(--accent); color: var(--text-on-accent); border-color: transparent; }
.panel-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; flex-wrap: wrap; }
.hint { color: var(--text-tertiary); font-size: 12px; }
.loading, .empty { color: var(--text-tertiary); padding: 20px; }
.script-list { display: flex; flex-direction: column; gap: 12px; }
.script-card {
  background: var(--bg-surface); border: 1px solid var(--border-default);
  border-radius: 10px; padding: 14px;
}
.script-head { display: flex; justify-content: space-between; gap: 12px; }
.script-name { font-weight: 600; font-size: 15px; color: var(--text-primary); }
.script-desc { color: var(--text-tertiary); font-size: 13px; margin-top: 4px; }
.script-err { color: var(--danger); font-size: 12px; margin-top: 4px; }
.script-cookies { color: var(--warning); font-size: 12px; margin-top: 4px; }
.script-actions { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.script-panel {
  margin: 14px 0 0; background: var(--bg-base);
  border: 1px solid var(--border-default); border-radius: 10px;
  overflow: hidden; min-height: 320px;
}
.script-panel-frame {
  width: 100%; height: 420px; border: none; background: #fff; display: block;
}
.switch { display: flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-tertiary); cursor: pointer; }
.run-form {
  margin: 14px auto 0; background: var(--bg-base);
  border: 1px solid var(--border-default); border-radius: 10px;
  padding: 16px; max-width: 720px;
}
.run-form-title {
  font-size: 13px; font-weight: 600; color: var(--text-secondary); margin-bottom: 14px;
  padding-bottom: 8px; border-bottom: 1px solid var(--border-default);
}
.form-row {
  margin-bottom: 14px; display: grid; grid-template-columns: 150px 1fr;
  column-gap: 14px; row-gap: 4px; align-items: start;
}
.form-row > label { font-size: 13px; color: var(--text-secondary); text-align: right; padding-top: 9px; }
.form-row > input[type="checkbox"] { justify-self: start; margin-top: 9px; width: 16px; height: 16px; accent-color: var(--accent); }
.req { color: var(--danger); }
.defaultable-tag {
  margin-left: 6px;
  padding: 1px 6px;
  font-size: 11px;
  color: var(--info);
  border: 1px solid var(--info);
  border-radius: 8px;
  background: color-mix(in srgb, var(--info) 10%, transparent);
}
.default-hint { margin-top: 8px; color: var(--success); font-size: 12px; }
.param-hint { grid-column: 2; color: var(--text-secondary); font-size: 12px; }
.multi-enum { display: flex; flex-wrap: wrap; gap: 8px 16px; align-items: center; }
.checkbox-inline {
  display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--text-secondary);
  cursor: pointer;
}
.checkbox-inline input { width: 15px; height: 15px; accent-color: var(--accent); }
.custom-input {
  background: var(--bg-surface); color: var(--text-primary);
  border: 1px dashed var(--border-default); border-radius: 8px; padding: 6px 10px;
  font-size: 13px; min-width: 180px;
}
.form-row input[type="text"], .form-row select, .form-row textarea,
.enum-editable input {
  background: var(--bg-surface); color: var(--text-primary);
  border: 1px solid var(--border-default); border-radius: 8px; padding: 8px 10px; font-size: 14px;
}
.form-row input[type="text"], .form-row select, .form-row textarea,
.enum-editable, .multi-enum { width: 100%; box-sizing: border-box; }
.run-buttons {
  display: flex; gap: 10px; margin-top: 10px; justify-content: flex-end;
  border-top: 1px solid var(--border-default); padding-top: 14px;
}
.job-interaction {
  margin-top: 14px; padding: 14px; border-radius: 10px;
  background: var(--accent-soft); border: 1px solid var(--border-default);
}
.interaction-prompt { font-size: 14px; font-weight: 600; color: var(--text-primary); margin-bottom: 12px; }
.interaction-options { display: flex; flex-direction: column; gap: 8px; }
.radio-inline { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-secondary); cursor: pointer; }
.radio-inline input { width: 15px; height: 15px; accent-color: var(--accent); }
.action-btn {
  padding: 7px 14px; border-radius: 8px; border: 1px solid var(--border-default);
  background: var(--bg-surface); color: var(--text-primary); cursor: pointer; font-size: 14px;
}
.action-btn.primary { background: var(--accent); color: var(--text-on-accent); border-color: transparent; }
.action-btn.primary:hover { background: var(--accent-active); }
.action-btn.danger { color: var(--danger); }
.action-btn:disabled { opacity: .5; cursor: not-allowed; }
.job-progress { margin-top: 14px; }
.progress-bar { height: 8px; background: var(--bg-surface-hover); border-radius: 6px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--accent); transition: width .3s; }
.progress-text { font-size: 13px; color: var(--text-secondary); margin: 8px 0; }
.job-error { color: var(--danger); font-size: 13px; }
.job-logs {
  background: var(--bg-base); border: 1px solid var(--border-default); border-radius: 8px;
  padding: 10px; max-height: 240px; overflow: auto; font-family: monospace; font-size: 12px;
}
.log-line { margin-bottom: 3px; color: var(--text-tertiary); }
.log-line.error { color: var(--danger); }
.log-line.log { color: var(--info); }
.log-ts { color: var(--text-tertiary); }
.data-table { width: 100%; border-collapse: collapse; margin-top: 8px; }
.data-table th, .data-table td {
  text-align: left; padding: 10px; border-bottom: 1px solid var(--border-default); font-size: 13px;
}
.data-table th { color: var(--text-secondary); font-weight: 600; }
.modal-mask {
  position: fixed; inset: 0; background: rgba(0,0,0,.45); display: flex; align-items: center; justify-content: center; z-index: 50;
}
.modal {
  background: var(--bg-surface); border: 1px solid var(--border-default); border-radius: 12px;
  padding: 20px; width: 480px; max-width: 92vw;
}
.modal-title { font-size: 16px; font-weight: 600; margin-bottom: 14px; color: var(--text-primary); }
.modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 16px; }
@media (max-width: 560px) {
  .form-row { grid-template-columns: 1fr; row-gap: 6px; }
  .form-row > label { text-align: left; padding-top: 0; }
  .run-form { max-width: 100%; margin: 14px 0 0; }
  .script-head { flex-direction: column; align-items: stretch; }
  .script-actions { justify-content: flex-end; flex-wrap: wrap; }
  .switch { flex-shrink: 0; }
  .data-table { display: block; overflow-x: auto; white-space: nowrap; -webkit-overflow-scrolling: touch; }
  .data-table th, .data-table td { white-space: nowrap; }
  .run-buttons { flex-wrap: wrap; }
  .run-buttons .action-btn { flex: 1 1 auto; }
}
</style>
