<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { videoApi, comicApi } from '../api'
import { useVideoStore } from '../stores/videoStore'
import { useComicStore } from '../stores/comicStore'

const props = defineProps<{
  visible: boolean
  type: 'video' | 'comic'
  item: any
}>()
const emit = defineEmits<{
  'update:visible': [boolean]
  saved: [any]
}>()

const videoStore = useVideoStore()
const comicStore = useComicStore()

const libraries = computed(() => (props.type === 'video' ? videoStore.libraries : comicStore.libraries))
const isVideo = computed(() => props.type === 'video')

const form = ref({
  title: '',
  description: '',
  priority: 0,
  library_id: '' as string,
  tags: [] as string[]
})
const saving = ref(false)
const errorMsg = ref('')
const tagInput = ref('')

watch(
  () => [props.visible, props.item],
  () => {
    if (props.visible && props.item) {
      const it = props.item
      form.value = {
        title: it.title || '',
        description: it.description || '',
        priority: it.priority ?? 0,
        library_id: it.library_id != null ? String(it.library_id) : '',
        tags: (it.tags || [])
          .map((t: any) => (t.path ? t.path : t.name ? '/' + t.name : ''))
          .filter(Boolean)
      }
      tagInput.value = ''
      errorMsg.value = ''
    }
  },
  { immediate: true }
)

const normalizeTag = (s: string): string => {
  s = s.trim()
  if (!s) return ''
  return s.startsWith('/') ? s : '/' + s
}

const addTag = () => {
  const t = normalizeTag(tagInput.value)
  if (t && !form.value.tags.includes(t)) form.value.tags.push(t)
  tagInput.value = ''
}
const removeTag = (t: string) => {
  form.value.tags = form.value.tags.filter((x) => x !== t)
}

const close = () => emit('update:visible', false)

// 把文件名（去扩展名）填入标题，交由管理员确认后点“保存”生效
const syncFromFilename = () => {
  const fn = props.item?.file_name || ''
  const dot = fn.lastIndexOf('.')
  form.value.title = dot > 0 ? fn.slice(0, dot) : fn
}

const save = async () => {
  if (!props.item) return
  saving.value = true
  errorMsg.value = ''
  try {
    const libId = form.value.library_id === '' ? null : Number(form.value.library_id)
    const hash = props.item.hash
    let savedTags: any[] = []
    if (isVideo.value) {
      await videoApi.updateVideo(hash, {
        title: form.value.title.trim(),
        description: form.value.description,
        priority: Number(form.value.priority) || 0,
        library_id: libId
      })
      const tagRes: any = await videoApi.setVideoTags(hash, form.value.tags)
      savedTags = tagRes?.tags || form.value.tags.map((p: string) => ({ name: p.split('/').pop(), path: p }))
    } else {
      await comicApi.updateComic(hash, {
        title: form.value.title.trim(),
        library_id: libId
      })
      const tagRes: any = await comicApi.setComicTags(hash, form.value.tags)
      savedTags = tagRes?.tags || form.value.tags.map((p: string) => ({ name: p.split('/').pop(), path: p }))
    }
    const updated = {
      ...props.item,
      title: form.value.title.trim(),
      description: form.value.description,
      priority: Number(form.value.priority) || 0,
      library_id: libId,
      tags: savedTags
    }
    emit('saved', updated)
    close()
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.message || e?.message || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="drawer-mask" @click="close">
      <div class="edit-drawer" @click.stop>
        <div class="drawer-header">
          <h3>编辑{{ isVideo ? '视频' : '漫画' }}</h3>
          <button class="drawer-close" @click="close" title="关闭">×</button>
        </div>

        <div class="drawer-body">
          <label class="field">
            <span class="field-label">标题</span>
            <div class="title-input-row">
              <input v-model="form.title" class="field-input" type="text" placeholder="标题" />
              <button v-if="isVideo" type="button" class="sync-filename-btn" title="用文件名填充标题" @click="syncFromFilename">↺ 同步文件名</button>
            </div>
          </label>

          <label v-if="isVideo" class="field">
            <span class="field-label">简介</span>
            <textarea v-model="form.description" class="field-textarea" rows="3" placeholder="简介"></textarea>
          </label>

          <label v-if="isVideo" class="field">
            <span class="field-label">优先级（0-100）</span>
            <input v-model.number="form.priority" class="field-input" type="number" min="0" max="100" />
          </label>

          <label class="field">
            <span class="field-label">所属视频库</span>
            <select v-model="form.library_id" class="field-input">
              <option value="">未分类 / 全局</option>
              <option v-for="lib in libraries" :key="lib.id" :value="String(lib.id)">
                {{ lib.name }}
              </option>
            </select>
          </label>

          <div class="field">
            <span class="field-label">标签（层级用 / 分隔，回车添加）</span>
            <div class="tag-edit-list">
              <span v-for="t in form.tags" :key="t" class="tag-edit-chip">
                {{ t }}
                <button class="tag-edit-remove" @click="removeTag(t)">×</button>
              </span>
              <input
                v-model="tagInput"
                class="tag-edit-input"
                type="text"
                placeholder="如 /分类/子分类"
                @keyup.enter="addTag"
              />
            </div>
          </div>

          <p v-if="errorMsg" class="drawer-error">{{ errorMsg }}</p>
        </div>

        <div class="drawer-footer">
          <button class="drawer-btn cancel" @click="close">取消</button>
          <button class="drawer-btn save" :disabled="saving" @click="save">
            {{ saving ? '保存中...' : '保存' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.drawer-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.55);
  z-index: 1000;
  display: flex;
  justify-content: flex-end;
}
.edit-drawer {
  width: 420px;
  max-width: 92vw;
  height: 100%;
  background: #1e1e1e;
  border-left: 1px solid #333;
  display: flex;
  flex-direction: column;
  box-shadow: -8px 0 32px rgba(0, 0, 0, 0.4);
}
.drawer-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 20px;
  border-bottom: 1px solid #2c2c2c;
}
.drawer-header h3 {
  margin: 0;
  color: #fff;
  font-size: 16px;
}
.drawer-close {
  background: transparent;
  border: none;
  color: #aaa;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
}
.drawer-close:hover {
  color: #fff;
}
.drawer-body {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field-label {
  color: #bbb;
  font-size: 13px;
}
.field-input {
  height: 40px;
  padding: 0 12px;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  background: #161616;
  color: #fff;
  font-size: 14px;
}

.title-input-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.sync-filename-btn {
  flex-shrink: 0;
  height: 40px;
  padding: 0 12px;
  border: 1px solid #3a5a7a;
  border-radius: 8px;
  background: rgba(33, 150, 243, 0.12);
  color: #9ecbff;
  font-size: 13px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.15s;
}

.sync-filename-btn:hover {
  background: #2196f3;
  color: #fff;
}
.field-textarea {
  padding: 10px 12px;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  background: #161616;
  color: #fff;
  font-size: 14px;
  resize: vertical;
  font-family: inherit;
}
.field-input:focus,
.field-textarea:focus {
  outline: none;
  border-color: #2196f3;
}
.tag-edit-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 8px;
  border: 1px solid #3a3a3a;
  border-radius: 8px;
  background: #161616;
}
.tag-edit-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 5px 10px;
  background: rgba(33, 150, 243, 0.12);
  border: 1px solid rgba(33, 150, 243, 0.3);
  border-radius: 8px;
  color: #cfe6ff;
  font-size: 13px;
}
.tag-edit-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  margin-left: 2px;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #9ecbff;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  transition: all 0.15s;
}
.tag-edit-remove:hover {
  background: #ef4444;
  color: #fff;
}
.tag-edit-input {
  flex: 1;
  min-width: 140px;
  border: none;
  background: transparent;
  color: #fff;
  font-size: 13px;
  outline: none;
}
.drawer-error {
  color: #ff6b6b;
  font-size: 13px;
  margin: 0;
}
.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 16px 20px;
  border-top: 1px solid #2c2c2c;
}
.drawer-btn {
  height: 38px;
  padding: 0 20px;
  border-radius: 8px;
  border: none;
  font-size: 14px;
  cursor: pointer;
}
.drawer-btn.cancel {
  background: #2a2a2a;
  color: #ccc;
}
.drawer-btn.save {
  background: #2196f3;
  color: #fff;
}
.drawer-btn.save:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
</style>
