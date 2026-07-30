// 视频类型
export interface Video {
  id: number
  hash: string
  title: string
  file_name?: string
  description?: string
  url: string
  thumbnail?: string
  duration?: number
  file_size?: number
  view_count: number
  like_count: number
  favorite_count?: number
  download_count: number
  priority: number
  min_role: number
  min_role_name: string
  is_downloaded: boolean
  local_path?: string
  owner_id?: number | null
  disliked?: boolean
  is_favorited?: boolean
  is_liked?: boolean
  is_disliked?: boolean
  tags: Tag[]
  created_at?: string
  updated_at?: string
}

// 精彩片段标记（用户个人时间戳）
export interface VideoMarker {
  id: number
  video_id: number
  time_seconds: number
  note: string | null
  created_at: string | null
}

// 标签类型 - 支持多级标签
export interface Tag {
  id: number
  name: string
  category?: string
  parent_id?: number | null
  video_count: number
  qualifiers?: string[]   // 补充项（标签维度预设的属性池，如 ["白","长毛"]）
  children?: Tag[]
}

// 视频上某个标签的关联（含选中的补充项）
export interface VideoTagRef {
  id: number
  name: string
  path: string
  qualifiers?: string[]          // 标签预设池
  selected_qualifiers?: string[] // 该视频在此标签上勾选的补充项
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

// 图集类型
export interface GalleryPage {
  index: number
  url: string
}

export interface Gallery {
  id: number
  hash: string
  title: string
  page_count: number
  library_id: number | null
  owner_id?: number | null
  cover_url: string
  like_count: number
  favorite_count: number
  is_liked?: boolean
  is_favorited?: boolean
  is_disliked?: boolean
  last_page?: number
  progress?: number
  in_continue?: boolean
  pages?: GalleryPage[]
  created_at?: string
  updated_at?: string
}

// 图集列表响应
export interface GalleryListResponse {
  success: boolean
  galleries: Gallery[]
  total: number
}

// 图集合集项
export interface GalleryPlaylistItem {
  id: number
  playlist_id: number
  gallery_id: number
  gallery: Gallery | null
  position: number
  added_at?: string
}

// 图集合集（播放列表）
export interface GalleryPlaylist {
  id: number
  name: string
  description?: string
  user_session: string
  is_public: boolean
  thumbnail?: string
  gallery_count: number
  play_count: number
  items: GalleryPlaylistItem[]
  created_at?: string
  updated_at?: string
}

// ============ 合集（独立于收藏夹，视频+图集通用）============
export interface CollectionItem {
  id: number
  collection_id: number
  item_type: 'video' | 'gallery'
  item_hash: string
  position: number
  added_at?: string
  media: any  // 解析后的视频/图集信息（含 type/hash/title/cover 等）
}

export interface Collection {
  id: number
  owner_key?: string
  name: string
  description?: string
  is_public?: boolean
  position: number
  item_count: number
  created_at?: string
  updated_at?: string
  item_position?: number | null  // 反向查询时：该资源在合集内的排序位
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

// 意见建议 / Issue（参考 GitHub Issue 风格）
export interface IssueComment {
  author: string
  author_role: number
  content: string
  created_at: string
}

export interface Issue {
  id: string                                   // yyyymmdd + 4 位流水号，如 202607250004
  title: string
  content: string
  type: 'bug' | 'suggestion' | 'other'         // 问题类型：缺陷 / 建议 / 其他
  author: string
  author_id: number | null
  author_role: number
  contact?: string                             // 仅管理员可见
  status: 'open' | 'closed'
  closed_reason: 'resolved' | 'dismissed' | null
  comments: IssueComment[]
  created_at: string
  updated_at: string
  closed_at: string | null
}

export interface IssueListResponse {
  success: boolean
  issues: Issue[]
  total: number
  open_count: number
  closed_count: number
  page: number
  page_size: number
}

// ============ 资源索引（通用资产）与模式归属 ============
export interface ResourcePresentation {
  title?: string
  thumbnail?: string
  duration?: number
  width?: number
  height?: number
  page_count?: number
  caption?: string
  summary?: string
  source_url?: string
  downloaded_by?: string
}

export interface ResourceIndex {
  id: number
  kind: string            // 'video_file' | 'gallery_folder' | 'text'
  location: string
  library_id?: number | null
  hash?: string
  meta?: any
  presentation?: ResourcePresentation
  modes?: string[]        // 该资源归属的模式
  updated_at?: string
}

export interface ModeCollection {
  id: number
  name: string
  mode: string
  library_id?: number | null
}

export interface TextResource {
  id: number
  resource_index_id: number
  body?: string
  summary?: string
  kind?: string
  location?: string
  presentation?: ResourcePresentation
  updated_at?: string
}

export interface AvailableMode {
  mode: string
  count: number
}

// ============ 帖子（Post）：通过资源索引表自由引用视频 / 图片集（图集）/ 文本 ============
export interface PostRef {
  ref_id: number
  position: number
  note: string
  resource_index_id: number
  display_mode?: 'link' | 'embed'   // 'link' 仅超链接 / 'embed' 超链接+内嵌预览
  kind?: string          // 'video_file' | 'gallery_folder' | 'text'
  location?: string
  video?: Video
  gallery?: Gallery
  text?: TextResource
  presentation?: ResourcePresentation   // 引用目标无富化实体时的兜底呈现
}

export interface Post {
  id: number
  title: string
  content: string
  owner_id?: number | null
  library_id?: number | null
  in_trash: boolean
  created_at?: string
  updated_at?: string
  refs: PostRef[]
}

