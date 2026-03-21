// 视频类型
export interface Video {
  id: number
  hash: string
  title: string
  description?: string
  url: string
  thumbnail?: string
  duration?: number
  file_size?: number
  view_count: number
  like_count: number
  download_count: number
  priority: number
  min_role: number
  min_role_name: string
  is_downloaded: boolean
  local_path?: string
  tags: Tag[]
  created_at?: string
  updated_at?: string
}

// 标签类型
export interface Tag {
  id: number
  name: string
  category?: string
  video_count: number
}

// 用户类型
export interface User {
  id: number
  username: string
  role: number
  role_name: string
  email?: string
  is_active: boolean
  created_at?: string
  last_login?: string
}

// API响应类型
export interface ApiResponse<T = unknown> {
  success: boolean
  message?: string
  data?: T
  code?: number
}

// 视频列表响应
export interface VideoListResponse {
  success: boolean
  videos: Video[]
  total: number
}

// 标签列表响应
export interface TagListResponse {
  success: boolean
  tags: Tag[]
}

// 配置类型
export interface AppConfig {
  scan_directories: ScanDirectory[]
  auto_scan_on_startup: boolean
  supported_formats: string[]
  default_tags: string[]
  default_priority: number
  ports: {
    web: number
    thumbnail: number
  }
}

export interface ScanDirectory {
  path: string
  recursive: boolean
  enabled: boolean
}

// 系统状态
export interface SystemStatus {
  success: boolean
  status: string
  database: {
    videos: number
    tags: number
  }
  timestamp: string
}

// 缩略图任务状态
export interface ThumbnailTask {
  task_id: string
  status: 'pending' | 'processing' | 'completed' | 'failed'
  error?: string
  thumbnail_path?: string
}

// 角色枚举
export enum UserRole {
  GUEST = 0,
  USER = 1,
  ADMIN = 2,
  ROOT = 3
}
