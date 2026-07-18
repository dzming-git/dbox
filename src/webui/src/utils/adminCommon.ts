// 管理后台各 Tab 组件共用的纯展示工具函数，集中于此避免重复定义

export const formatDate = (dateStr: string) => {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

export const getRoleClass = (role: number) => {
  const roleMap: Record<number, string> = {
    0: 'guest',
    1: 'user',
    2: 'admin',
    3: 'root'
  }
  return roleMap[role] || 'user'
}

export const formatPath = (path: string, maxLength: number = 50) => {
  if (!path) return '-'
  if (path.length <= maxLength) return path
  return '...' + path.slice(-maxLength + 3)
}

export const formatFileSize = (bytes: number) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(2)} ${units[unitIndex]}`
}

export const formatBytes = (bytes: number): string => {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i]
}

export const getUsageClass = (percent: number | undefined): string => {
  if (percent === undefined) return ''
  if (percent >= 90) return 'danger'
  if (percent >= 70) return 'warning'
  return 'normal'
}

export const formatUptime = (seconds: number): string => {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const parts: string[] = []
  if (days > 0) parts.push(`${days} 天`)
  if (hours > 0) parts.push(`${hours} 小时`)
  if (minutes > 0) parts.push(`${minutes} 分钟`)
  return parts.join(' ') || '不到 1 分钟'
}

export const getPriorityColor = (priority: number) => {
  if (priority >= 80) return '#ff4d4f'
  if (priority >= 60) return '#faad14'
  if (priority >= 40) return '#1890ff'
  if (priority >= 20) return '#52c41a'
  return '#8c8c8c'
}

export const getPriorityLabel = (priority: number) => {
  if (priority >= 80) return '极高'
  if (priority >= 60) return '高'
  if (priority >= 40) return '中'
  if (priority >= 20) return '低'
  return '极低'
}
