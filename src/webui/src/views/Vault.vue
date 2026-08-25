<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { scriptApi, type CookieProfile } from '../api/script'
import BaseModal from '../components/BaseModal.vue'

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

onMounted(load)
</script>

<template>
  <div class="vault-page">
    <div class="page-head">
      <h2>凭证保险库</h2>
      <button class="btn-primary" @click="openCreate">新增凭证</button>
    </div>

    <p class="hint">
      统一管理各子系统（插件、下载器等）所需的 Cookie / Token / 密码 / API Key。
      凭证明文加密落盘，此处仅展示元信息，不回显密文内容。
    </p>

    <div v-if="errorMsg" class="error-msg">{{ errorMsg }}</div>

    <div v-if="loading" class="loading">加载中…</div>

    <div v-else-if="!profiles.length" class="empty">暂无凭证，点击右上角「新增凭证」添加。</div>

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
