<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '../api'
import { useToast } from '../composables/useToast'

const { showToast } = useToast()

const systemConfig = ref({
  max_upload_size: 1024,
  thumbnail_quality: 85,
  auto_sync: true,
  allow_register: false
})

const fetchSystemConfig = async () => {
  try {
    const res = await api.get('/api/admin/config') as any
    if (res.success) {
      systemConfig.value = { ...systemConfig.value, ...res.config }
    }
  } catch (error) {
    console.error('获取系统配置失败:', error)
  }
}

const saveSystemConfig = async () => {
  try {
    const res = await api.post('/api/admin/config', systemConfig.value) as any
    if (res.success) {
      showToast('配置已保存')
    }
  } catch (error) {
    console.error('保存系统配置失败:', error)
    showToast('保存失败')
  }
}

onMounted(() => {
  fetchSystemConfig()
})
</script>

<template>
  <div class="tab-content">
    <div class="section-header">
      <h3>系统配置</h3>
    </div>

    <div class="config-form">
      <div class="form-group">
        <label>最大上传大小 (MB)</label>
        <input
          v-model.number="systemConfig.max_upload_size"
          type="number"
          min="1"
          max="10240"
        />
      </div>
      <div class="form-group">
        <label>缩略图质量 (1-100)</label>
        <input
          v-model.number="systemConfig.thumbnail_quality"
          type="number"
          min="1"
          max="100"
        />
      </div>
      <div class="form-group">
        <label>自动同步</label>
        <label class="switch">
          <input v-model="systemConfig.auto_sync" type="checkbox" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="form-group">
        <label>允许注册</label>
        <label class="switch">
          <input v-model="systemConfig.allow_register" type="checkbox" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="form-actions">
        <button class="action-btn primary" @click="saveSystemConfig">保存配置</button>
      </div>
    </div>
  </div>
</template>
