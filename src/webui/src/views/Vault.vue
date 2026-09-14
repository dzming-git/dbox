<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { scriptApi, type CookieProfile } from '../api/script'
import BaseModal from '../components/BaseModal.vue'

// embedded：作为后台「应用」标签页内嵌时，隐藏自身页面标题（标题由后台统一提供）
const props = defineProps<{ embedded?: boolean }>()

const loading = ref(false)
const profiles = ref<CookieProfile[]>([])
const errorMsg = ref('')

// 新增/编辑弹窗
const showForm = ref(false)
const editingId = ref<string | null>(null)
const form = ref({
  kind: 'cookie',
  name: '',
  domain: '',
  note: '',
  value: '',      // 标量凭证用
  cookies: ''     // cookie 凭证用：header 字符串，形如 "auth_token=xxx; ct0=yyy"
})
const saving = ref(false)

const kindLabel: Record<string, string> = {
  cookie: 'Cookie',
  token: 'Token',
  password: '密码',
  apikey: 'API Key'
}

const isEditing = computed(() => editingId.value !== null)

async function load() {
  loading.value = true
  errorMsg.value = ''
  try {
    const res: any = await scriptApi.listCookies()
    profiles.value = res?.cookies || []
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.message || '加载凭证失败'
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editingId.value = null
  form.value = { kind: 'cookie', name: '', domain: '', note: '', value: '', cookies: '' }
  showForm.value = true
}

async function openEdit(p: CookieProfile) {
  editingId.value = p.id
  // 先打开弹窗并填入元信息；Cookie 明文需经详情接口拉取后再预填，
  // 避免编辑时文本框为空导致用户重新粘贴漏粘/粘错（已知 bug）。
  form.value = {
    kind: p.kind || 'cookie',
    name: p.name || '',
    domain: p.domain || '',
    note: p.note || '',
    value: '',
    cookies: ''
  }
  showForm.value = true
  try {
    const res: any = await scriptApi.getCookie(p.id)
    const c = res?.cookie
    if (c) {
      if (c.kind === 'cookie') {
        form.value.cookies = c.cookies_header || ''
      } else {
        form.value.value = c.value || ''
      }
    }
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.message || '加载凭证内容失败'
  }
}

async function submit() {
  const f = form.value
  if (!f.domain.trim()) {
    errorMsg.value = '请填写域名'
    return
  }
  saving.value = true
  errorMsg.value = ''
  try {
    const payload: any = {
      kind: f.kind,
      name: f.name.trim(),
      domain: f.domain.trim(),
      note: f.note.trim(),
      format: 'netscape'
    }
    if (f.kind === 'cookie') {
      if (!f.cookies.trim()) { errorMsg.value = '请填写 Cookie 内容'; saving.value = false; return }
      payload.cookies = f.cookies.trim()
    } else {
      if (!f.value) { errorMsg.value = '请填写凭证值'; saving.value = false; return }
      payload.value = f.value
    }
    if (isEditing.value && editingId.value) {
      await scriptApi.updateCookie(editingId.value, payload)
    } else {
      await scriptApi.createCookie(payload)
    }
    showForm.value = false
    await load()
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.message || '保存失败'
  } finally {
    saving.value = false
  }
}

async function remove(p: CookieProfile) {
  if (!confirm(`确认删除凭证「${p.name || p.domain}」？`)) return
  try {
    await scriptApi.deleteCookie(p.id)
    await load()
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.message || '删除失败'
  }
}

// ============ 健康度与重新登录 ============
const fmtDate = (s?: string) => (s ? new Date(s).toLocaleString('zh-CN') : '')
const health = ref<any>(null)

async function loadHealth() {
  try {
    const r: any = await scriptApi.cookiesHealth()
    health.value = r?.success ? r : null
  } catch {
    health.value = null
  }
}

const STATUS_META: Record<string, { label: string; cls: string }> = {
  ok: { label: '正常', cls: 'ok' },
  expiring: { label: '即将过期', cls: 'warn' },
  expired: { label: '已失效', cls: 'bad' },
  unknown: { label: '待确认', cls: 'unknown' },
}

// 分组视图：有健康数据时按站点分组，否则退回平铺列表
const grouped = computed(() => (health.value?.groups?.length ? true : false))
const statusOf = (id: string) => {
  for (const g of health.value?.groups || []) {
    const hit = (g.items || []).find((x: any) => x.id === id)
    if (hit) return hit
  }
  return null
}

const relinking = ref<string | null>(null)
let relinkTimer: any = null

async function relink(p: any) {
  if (relinking.value) return
  if (!confirm(`将打开浏览器登录「${p.domain}」，完成后会自动写回保险库。继续？`)) return
  try {
    const r: any = await scriptApi.relinkCookie({ id: p.id, domain: p.domain })
    if (!r?.success) {
      alert(r?.message || '无法打开登录页')
      return
    }
    relinking.value = r.sid
    pollRelink(r.sid)
  } catch (e: any) {
    alert(e?.response?.data?.message || '启动登录失败')
  }
}

function pollRelink(sid: string) {
  if (relinkTimer) clearInterval(relinkTimer)
  relinkTimer = setInterval(async () => {
    try {
      const s: any = await scriptApi.relinkStatus(sid)
      const state = s?.state
      if (state === 'done') {
        stopRelink()
        const c: any = await scriptApi.relinkCommit(sid)
        alert(c?.success ? `已更新，写入 ${c.cookie_count} 条 Cookie` : (c?.message || '写入失败'))
        await load()
        await loadHealth()
      } else if (state === 'error' || state === 'timeout' || state === 'cancelled') {
        stopRelink()
        alert(`登录未成功：${s?.error || state}`)
      }
    } catch {
      stopRelink()
    }
  }, 2000)
}

function stopRelink() {
  if (relinkTimer) clearInterval(relinkTimer)
  relinkTimer = null
  relinking.value = null
}

onUnmounted(stopRelink)

onMounted(() => {
  load()
  loadHealth()
})
</script>

<template>
  <div class="vault-page">
    <div class="page-head">
      <h2 v-if="!props.embedded">凭证保险库</h2>
      <button class="btn-primary" @click="openCreate">新增凭证</button>
    </div>

    <p class="hint">
      统一管理各子系统（插件、下载器等）所需的 Cookie / Token / 密码 / API Key。
      凭证明文加密落盘，此处仅展示元信息，不回显密文内容。
    </p>

    <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!profiles.length" class="empty">暂无凭证，点击右上角「新增凭证」添加。</div>

    <!-- 健康度概览：有问题时一眼看到，而不是等某次任务失败才发现 -->
    <div v-if="health?.summary" class="health-bar">
      <span class="hb-item ok">正常 {{ health.summary.ok || 0 }}</span>
      <span class="hb-item warn">即将过期 {{ health.summary.expiring || 0 }}</span>
      <span class="hb-item bad">已失效 {{ health.summary.expired || 0 }}</span>
      <span class="hb-item unknown">待确认 {{ health.summary.unknown || 0 }}</span>
    </div>

    <div v-else class="profile-list">
      <div v-for="p in profiles" :key="p.id" class="profile-card">
        <div class="profile-main">
          <span class="kind-badge">{{ kindLabel[p.kind || 'cookie'] || p.kind }}</span>
          <span class="profile-name">{{ p.name || p.domain }}</span>
          <span class="profile-domain">{{ p.domain }}</span>
        </div>
        <div class="profile-meta">
          <span v-if="p.note" class="note">{{ p.note }}</span>
          <span class="status" :class="{ ok: p.has_value }">{{ p.has_value ? '已配置' : '未配置' }}</span>
        </div>
        <div class="profile-actions">
          <button class="btn-text" @click="openEdit(p)">编辑</button>
          <button class="btn-text danger" @click="remove(p)">删除</button>
        </div>
      </div>
    </div>

    <!-- 按站点分组（健康视图） -->
    <div v-if="grouped" class="group-list">
      <div v-for="g in health.groups" :key="g.domain" class="group">
        <div class="group-head">
          <span class="group-domain">{{ g.domain }}</span>
          <span class="health-dot" :class="STATUS_META[g.status]?.cls || 'unknown'"></span>
          <span class="group-count">{{ g.items.length }} 条</span>
        </div>
        <div v-for="it in g.items" :key="it.id" class="group-item">
          <div class="gi-main">
            <span class="kind-badge">{{ kindLabel[it.kind || 'cookie'] || it.kind }}</span>
            <span class="gi-name">{{ it.name || it.domain }}</span>
            <span
              class="health-tag"
              :class="STATUS_META[it.status]?.cls || 'unknown'"
              :title="it.message"
            >{{ STATUS_META[it.status]?.label || it.status }}</span>
          </div>
          <div class="gi-meta">
            <span v-if="it.message" class="gi-msg">{{ it.message }}</span>
            <span v-if="it.last_used_at" class="gi-used">最近使用 {{ fmtDate(it.last_used_at) }}</span>
          </div>
          <div class="profile-actions">
            <button
              v-if="it.kind === 'cookie'"
              class="btn-text"
              :disabled="!!relinking"
              @click="relink(it)"
              title="打开浏览器重新登录并写回"
            >{{ relinking ? '登录中…' : '重新登录' }}</button>
            <button class="btn-text" @click="openEdit({ id: it.id, kind: it.kind, name: it.name, domain: it.domain, note: it.note })">编辑</button>
            <button class="btn-text danger" @click="remove({ id: it.id, name: it.name, domain: it.domain })">删除</button>
          </div>
        </div>
      </div>
    </div>

    <!-- 新增/编辑弹窗：统一走 BaseModal（自适应尺寸 + 内部滚动 + 点外关闭 + 内容缓存） -->
    <BaseModal
      v-model:visible="showForm"
      :title="isEditing ? '编辑凭证' : '新增凭证'"
      max-width="460px"
      @close="errorMsg = ''"
    >
      <div class="form-field">
        <label>类型</label>
        <select v-model="form.kind">
          <option value="cookie">Cookie</option>
          <option value="token">Token</option>
          <option value="password">密码</option>
          <option value="apikey">API Key</option>
        </select>
      </div>

      <div class="form-field">
        <label>域名（如 x.com）</label>
        <input v-model="form.domain" placeholder="x.com" />
      </div>

      <div class="form-field">
        <label>名称（可选）</label>
        <input v-model="form.name" placeholder="用于识别，如「X 登录态」" />
      </div>

      <div v-if="form.kind === 'cookie'" class="form-field">
        <label>Cookie 内容（header 字符串）</label>
        <textarea v-model="form.cookies" rows="5" placeholder="auth_token=xxx; ct0=yyy; ..."></textarea>
      </div>
      <div v-else class="form-field">
        <label>凭证值</label>
        <textarea v-model="form.value" rows="3" placeholder="粘贴 token / 密码 / key"></textarea>
      </div>

      <div class="form-field">
        <label>备注（可选）</label>
        <input v-model="form.note" placeholder="用途说明" />
      </div>

      <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

      <template #footer>
        <button class="btn-ghost" @click="showForm = false">取消</button>
        <button class="btn-primary" :disabled="saving" @click="submit">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
/* 健康度 */
.health-bar { display: flex; gap: 14px; flex-wrap: wrap; margin: 12px 0 4px; font-size: 12px; }
.hb-item { padding: 3px 10px; border-radius: 999px; background: var(--bg-surface-2, #2a2f3a); }
.hb-item.ok { color: var(--success, #4ade80); }
.hb-item.warn { color: var(--warning, #fbbf24); }
.hb-item.bad { color: var(--danger, #ff6b70); }
.hb-item.unknown { color: var(--text-tertiary, #7c828f); }
.group-list { display: flex; flex-direction: column; gap: 14px; margin-top: 14px; }
.group { border: 1px solid var(--border-default, rgba(255,255,255,.1)); border-radius: 10px; overflow: hidden; }
.group-head { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: var(--bg-surface-2, #2a2f3a); font-size: 13px; }
.group-domain { font-weight: 600; }
.group-count { margin-left: auto; color: var(--text-tertiary, #7c828f); font-size: 12px; }
.health-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-tertiary, #7c828f); }
.health-dot.ok { background: var(--success, #4ade80); }
.health-dot.warn { background: var(--warning, #fbbf24); }
.health-dot.bad { background: var(--danger, #ff6b70); }
.group-item { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px 12px; border-top: 1px solid var(--border-subtle, rgba(255,255,255,.06)); }
.gi-main { display: flex; align-items: center; gap: 8px; flex: 1; min-width: 220px; }
.gi-name { font-size: 14px; }
.health-tag { font-size: 11px; padding: 1px 8px; border-radius: 999px; background: var(--bg-surface-2, #2a2f3a); color: var(--text-tertiary, #7c828f); }
.health-tag.ok { color: var(--success, #4ade80); }
.health-tag.warn { color: var(--warning, #fbbf24); }
.health-tag.bad { color: var(--danger, #ff6b70); }
.gi-meta { display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--text-tertiary, #7c828f); }
.gi-msg { color: var(--text-secondary, #b3b8c4); }
.vault-page { padding: 24px; max-width: 900px; margin: 0 auto; color: var(--text-primary, #eee); }
.page-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.page-head h2 { margin: 0; font-size: 20px; }
.hint { color: var(--text-tertiary, #999); font-size: 13px; margin: 0 0 20px; line-height: 1.6; }

.btn-primary { background: var(--accent, #4f8cff); color: #fff; border: none; border-radius: 8px; padding: 8px 16px; cursor: pointer; font-size: 14px; }
.btn-primary:disabled { opacity: 0.6; cursor: not-allowed; }
.btn-ghost { background: transparent; color: var(--text-secondary, #bbb); border: 1px solid var(--border-default, #444); border-radius: 8px; padding: 8px 16px; cursor: pointer; }
.btn-text { background: none; border: none; color: var(--accent, #4f8cff); cursor: pointer; font-size: 13px; padding: 4px 8px; }
.btn-text.danger { color: #f5455c; }

.error-msg { background: rgba(245, 69, 92, 0.12); color: #f5455c; border-radius: 8px; padding: 10px 14px; margin: 12px 0; font-size: 13px; }
.loading, .empty { color: var(--text-tertiary, #999); padding: 40px 0; text-align: center; }

.profile-list { display: flex; flex-direction: column; gap: 10px; }
.profile-card {
  display: flex; align-items: center; justify-content: space-between; gap: 16px;
  background: var(--bg-surface, #232329); border: 1px solid var(--border-subtle, #2e2e34);
  border-radius: 10px; padding: 14px 16px;
}
.profile-main { display: flex; align-items: center; gap: 10px; min-width: 0; }
.kind-badge { flex-shrink: 0; background: var(--bg-surface-2, #2a2a30); color: var(--text-secondary, #bbb); border-radius: 6px; padding: 2px 8px; font-size: 12px; }
.profile-name { font-weight: 600; white-space: nowrap; }
.profile-domain { color: var(--text-tertiary, #999); font-size: 13px; }
.profile-meta { display: flex; align-items: center; gap: 12px; color: var(--text-tertiary, #999); font-size: 12px; }
.profile-meta .note { max-width: 220px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.status { padding: 2px 8px; border-radius: 6px; background: rgba(255,255,255,0.06); }
.status.ok { background: rgba(52, 199, 123, 0.15); color: #34c77b; }
.profile-actions { display: flex; gap: 4px; flex-shrink: 0; }

/* 表单字段 */
.form-field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.form-field label { font-size: 13px; color: var(--text-secondary, #bbb); }
.form-field input, .form-field select, .form-field textarea {
  background: var(--bg-surface, #232329); border: 1px solid var(--border-subtle, #2e2e34);
  border-radius: 8px; padding: 8px 10px; color: var(--text-primary, #eee); font-size: 14px;
  font-family: inherit;
}
.form-field textarea { resize: vertical; min-height: 60px; }

/* 移动端：窄屏下卡片由横向一行改为纵向堆叠，避免元素重叠 */
@media (max-width: 640px) {
  .vault-page { padding: 16px 12px; }
  .page-head { flex-wrap: wrap; gap: 10px; }
  .profile-card {
    flex-direction: column;
    align-items: stretch;
    gap: 10px;
  }
  .profile-main { flex-wrap: wrap; }
  .profile-name, .profile-domain { white-space: normal; word-break: break-all; }
  .profile-meta { flex-wrap: wrap; }
  .profile-meta .note { max-width: none; white-space: normal; word-break: break-word; }
  .profile-actions { justify-content: flex-end; }
}
</style>
