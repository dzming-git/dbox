<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { api } from '../api'
import { useUserStore } from '../stores/userStore'
import { useToast } from '../composables/useToast'
import { formatDate, getRoleClass } from '../utils/adminCommon'

const { showToast } = useToast()
const userStore = useUserStore()

// ROOT 账号仅允许 ROOT 自身操作；普通管理员（ADMIN）不能创建/编辑/删除 ROOT
const canManageRoot = computed(() => userStore.isRoot)
const isRootUser = (u: any) => u.role >= 3

const users = ref<any[]>([])
const usersLoading = ref(false)
const showUserModal = ref(false)
const editingUser = ref<any>(null)
const userForm = ref({
  username: '',
  password: '',
  role: 'user'
})

const fetchUsers = async () => {
  usersLoading.value = true
  try {
    const res = await api.get('/api/admin/users') as any
    if (res.success) {
      users.value = res.users || []
    }
  } catch (error) {
    console.error('获取用户列表失败:', error)
  } finally {
    usersLoading.value = false
  }
}

const createUser = async () => {
  try {
    const res = await api.post('/api/admin/users', userForm.value) as any
    if (res.success) {
      showToast('创建成功')
      showUserModal.value = false
      fetchUsers()
      userForm.value = { username: '', password: '', role: 'user' }
    }
  } catch (error) {
    console.error('创建用户失败:', error)
    showToast('创建失败')
  }
}

const editUser = (user: any) => {
  editingUser.value = user
  userForm.value = {
    username: user.username,
    password: '',
    role: ['guest', 'user', 'admin', 'root'][user.role] || 'user'
  }
  showUserModal.value = true
}

const updateUser = async () => {
  if (!editingUser.value) return
  try {
    const updateData: any = {
      username: userForm.value.username,
      role: userForm.value.role
    }
    if (userForm.value.password) {
      updateData.password = userForm.value.password
    }

    const res = await api.put(`/api/admin/users/${editingUser.value.id}`, updateData) as any
    if (res.success) {
      showToast('更新成功')
      showUserModal.value = false
      editingUser.value = null
      userForm.value = { username: '', password: '', role: 'user' }
      fetchUsers()
    }
  } catch (error) {
    console.error('更新用户失败:', error)
    showToast('更新失败')
  }
}

const deleteUser = async (id: number) => {
  if (!confirm('确定要删除这个用户吗？')) return
  try {
    const res = await api.delete(`/api/admin/users/${id}`) as any
    if (res.success) {
      showToast('删除成功')
      fetchUsers()
    }
  } catch (error) {
    console.error('删除用户失败:', error)
    showToast('删除失败')
  }
}

// ============ 资源库权限控制 ============
const showPermModal = ref(false)
const permUser = ref<any>(null)
const permLibs = ref<any[]>([])
const permLoading = ref(false)
const permSaving = ref(false)

const LEVEL_OPTIONS = [
  { value: 'none', label: '无权限' },
  { value: 'read', label: '只读' },
  { value: 'write', label: '读写' },
]

const openPermModal = async (user: any) => {
  if (isRootUser(user)) {
    showToast('超级管理员默认拥有全部资源库权限，无需单独设置')
    return
  }
  permUser.value = user
  showPermModal.value = true
  permLoading.value = true
  permLibs.value = []
  try {
    const res = await api.get(`/api/admin/users/${user.id}/library-permissions`) as any
    if (res.success) {
      // 管理员账户后端返回 is_admin=true，前端禁用编辑
      permLibs.value = (res.libraries || []).map((lib: any) => ({
        library_id: lib.library_id,
        library_name: lib.library_name,
        // effective 为 admin/full 时视为可写并禁用
        level: lib.effective === 'write' || lib.effective === 'read' || lib.effective === 'admin' || lib.effective === 'full'
          ? (lib.effective === 'read' ? 'read' : (lib.effective === 'admin' || lib.effective === 'full' ? 'write' : 'read'))
          : (lib.direct_level || 'none'),
        locked: res.is_admin || lib.effective === 'admin' || lib.effective === 'full',
        effective: lib.effective,
      }))
    }
  } catch (error) {
    console.error('获取资源库权限失败:', error)
    showToast('获取资源库权限失败')
  } finally {
    permLoading.value = false
  }
}

const savePerms = async () => {
  if (!permUser.value) return
  permSaving.value = true
  try {
    const permissions = permLibs.value
      .filter((l) => !l.locked)
      .map((l) => ({ library_id: l.library_id, level: l.level }))
    const res = await api.post(`/api/admin/users/${permUser.value.id}/library-permissions`, { permissions }) as any
    if (res.success) {
      showToast('资源库权限已保存')
      showPermModal.value = false
    } else {
      showToast(res.message || '保存失败')
    }
  } catch (error) {
    console.error('保存资源库权限失败:', error)
    showToast('保存失败')
  } finally {
    permSaving.value = false
  }
}

onMounted(() => {
  fetchUsers()
})
</script>

<template>
  <div class="tab-content">
    <div class="section-header">
      <h3>用户管理</h3>
      <button class="action-btn primary" @click="showUserModal = true">+ 添加用户</button>
    </div>

    <div class="data-table-container">
      <table class="data-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>用户名</th>
            <th>角色</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>{{ user.id }}</td>
            <td>{{ user.username }}</td>
            <td>
              <span class="role-tag" :class="getRoleClass(user.role)">{{ user.role_name }}</span>
            </td>
            <td>{{ formatDate(user.created_at) }}</td>
            <td>
              <button
                class="icon-btn"
                title="资源库权限"
                @click="openPermModal(user)"
                v-if="user.id !== userStore.user?.id && (canManageRoot || !isRootUser(user))"
              >
                🔐
              </button>
              <button
                class="icon-btn"
                @click="editUser(user)"
                v-if="user.id !== userStore.user?.id && (canManageRoot || !isRootUser(user))"
              >
                ✏️
              </button>
              <button
                class="icon-btn danger"
                @click="deleteUser(user.id)"
                v-if="user.id !== userStore.user?.id && (canManageRoot || !isRootUser(user))"
              >
                🗑️
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div v-if="usersLoading" class="loading-text">加载中...</div>
      <div v-else-if="users.length === 0" class="empty-text">暂无用户</div>
    </div>

    <!-- 用户创建/编辑弹窗 -->
    <div v-if="showUserModal" class="modal-overlay" @click="showUserModal = false">
      <div class="modal-content" @click.stop>
        <div class="modal-header">
          <h3>{{ editingUser ? '编辑用户' : '添加用户' }}</h3>
          <button class="close-btn" @click="showUserModal = false">×</button>
        </div>
        <div class="modal-body">
          <div class="form-group">
            <label>用户名</label>
            <input v-model="userForm.username" type="text" />
          </div>
          <div class="form-group">
            <label>密码{{ editingUser ? '（留空表示不修改）' : '' }}</label>
            <input v-model="userForm.password" type="password" :placeholder="editingUser ? '留空表示不修改密码' : ''" />
          </div>
          <div class="form-group">
            <label>角色</label>
            <select v-model="userForm.role">
              <option value="user">普通用户</option>
              <option value="admin">管理员</option>
              <option value="root" :disabled="!canManageRoot">超级管理员</option>
            </select>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showUserModal = false">取消</button>
          <button class="action-btn primary" @click="editingUser ? updateUser() : createUser()">
            {{ editingUser ? '保存' : '创建' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 资源库权限控制弹窗 -->
    <div v-if="showPermModal" class="modal-overlay" @click="showPermModal = false">
      <div class="modal-content perm-modal" @click.stop>
        <div class="modal-header">
          <h3>资源库权限 - {{ permUser?.username }}</h3>
          <button class="close-btn" @click="showPermModal = false">×</button>
        </div>
        <div class="modal-body">
          <p class="perm-tip">为「{{ permUser?.username }}」设置每个资源库的访问权限：<b>只读</b>仅可浏览，<b>读写</b>可上传 / 增删文件夹。</p>
          <div v-if="permLoading" class="loading-text">加载中...</div>
          <div v-else class="perm-list">
            <div v-for="lib in permLibs" :key="lib.library_id" class="perm-row" :class="{ locked: lib.locked }">
              <span class="perm-name">{{ lib.library_name }}</span>
              <select
                v-model="lib.level"
                :disabled="lib.locked"
                class="perm-select"
              >
                <option v-for="opt in LEVEL_OPTIONS" :key="opt.value" :value="opt.value">{{ opt.label }}</option>
              </select>
              <span v-if="lib.locked" class="perm-locked-tag">管理员默认全权</span>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <button class="action-btn" @click="showPermModal = false">取消</button>
          <button class="action-btn primary" @click="savePerms" :disabled="permSaving">
            {{ permSaving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 弹窗：固定在视口中央，而非随页面流定位 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  overflow-y: auto;
  overscroll-behavior: contain;
  padding: 24px 16px;
}

.modal-content {
  background: var(--bg-surface);
  border-radius: 12px;
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  animation: modalIn 0.3s ease;
}

@keyframes modalIn {
  from { opacity: 0; transform: scale(0.9); }
  to { opacity: 1; transform: scale(1); }
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  border-bottom: 1px solid var(--border-default);
}

.modal-header h3 {
  margin: 0;
  font-size: 18px;
}

.close-btn {
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
  color: var(--text-tertiary);
}

.modal-body {
  padding: 20px;
  max-height: 60vh;
  overflow-y: auto;
  overscroll-behavior: contain;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid var(--border-default);
}

.perm-modal {
  max-width: 520px;
}
.perm-tip {
  font-size: 13px;
  color: var(--text-muted, #8a8f98);
  margin: 0 0 14px;
  line-height: 1.5;
}
.perm-tip b {
  color: var(--text-primary, #e6e8eb);
}
.perm-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 50vh;
  overflow-y: auto;
}
.perm-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-default, #2a2e37);
  border-radius: 8px;
}
.perm-row.locked {
  opacity: 0.55;
  background: var(--bg-subtle, #1c1f26);
}
.perm-name {
  flex: 1;
  font-weight: 500;
  color: var(--text-primary, #e6e8eb);
}
.perm-select {
  min-width: 110px;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--border-default, #2a2e37);
  background: var(--bg-input, #1a1d24);
  color: var(--text-primary, #e6e8eb);
}
.perm-locked-tag {
  font-size: 12px;
  color: var(--text-muted, #8a8f98);
  white-space: nowrap;
}
</style>
