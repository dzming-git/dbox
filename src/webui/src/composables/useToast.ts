import { ref } from 'vue'

// 全局 Toast 状态：父组件渲染宿主元素，各子组件通过 useToast().showToast 触发
const toastMessage = ref('')
const showToastFlag = ref(false)
let toastQueue: string[] = []

const showToast = (message: string) => {
  toastQueue.push(message)
  if (!showToastFlag.value) {
    showNextToast()
  }
}

const showNextToast = () => {
  if (toastQueue.length === 0) {
    showToastFlag.value = false
    return
  }
  toastMessage.value = toastQueue.shift()!
  showToastFlag.value = true
  setTimeout(() => {
    showToastFlag.value = false
    setTimeout(() => showNextToast(), 100)
  }, 2500)
}

export function useToast() {
  return { toastMessage, showToastFlag, showToast }
}
