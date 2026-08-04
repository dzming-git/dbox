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
  </div>
</template>
