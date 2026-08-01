import { reactive } from 'vue'
import api from '../api'
import { useToast } from './useToast'

export interface UploadTask {
  id: number
  fileName: string
  status: 'uploading' | 'done' | 'error'
  message: string
}

// 全局单例：上传任务脱离组件生命周期，组件卸载后请求仍在后台继续
const uploads = reactive<UploadTask[]>([])
let seq = 0

export function useUploadManager() {
  const start = (formData: FormData) => {
    const id = ++seq
    const file = formData.get('video')
    const fileName = file instanceof File ? file.name : '文件'
    uploads.push({ id, fileName, status: 'uploading', message: '上传中' })

    const { showToast } = useToast()

    api
      .post('/api/upload', formData, { timeout: 0 })
      .then(() => {
        const task = uploads.find((u) => u.id === id)
        if (task) {
          task.status = 'done'
          task.message = '上传完成'
        }
        showToast(`「${fileName}」上传完成，稍后可在视频库查看`)
      })
      .catch((e: any) => {
        const task = uploads.find((u) => u.id === id)
        if (task) {
          task.status = 'error'
          task.message = e?.response?.data?.message || '上传失败'
        }
        showToast(`「${fileName}」上传失败`)
      })
  }

  return { uploads, start }
}
