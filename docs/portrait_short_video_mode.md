# 竖屏全屏短视频模式（抖音式）实现方案

> 状态：实现中
> 关联：首页资源类型切换、Video.vue 播放页、视频互动 API

## 一、需求拆解

1. 视频播放页「横屏全屏」按钮旁新增「竖屏全屏」按钮，点击进入竖屏沉浸短视频模式。
2. 竖屏模式内：
   - 下滑 → 下一个随机视频；上滑 → 上一个视频（需记住历史，上行后再下行仍回到原视频）。
   - 双击 → 点赞。
   - 右侧竖排：点赞、收藏按钮；角落（右下/左下）放「不喜欢」按钮。
   - 有按钮可切「横屏全屏」（原生全屏）与「详情模式」（当前普通详情页）。
3. 竖屏模式是 CSS 模拟的 9:16 沉浸容器（非浏览器 Fullscreen API），以便自定义右侧操作栏与滑动手势。

## 二、技术方案

### 状态机（Video.vue）
- 新增 `playMode = ref<'normal' | 'portrait'>('normal')`，由路由 query `?mode=portrait` 初始化。
- 竖屏模式为覆盖全屏的 `.portrait-mode` 容器（fixed, 100vw/100vh, 黑底），内部独立渲染 `<video>` 与操作栏。

### 短视频流（feed）
- `feedList = ref<string[]>([])`：累积的视频 hash 序列。
- `feedIndex = ref(0)`：当前播放位置指针。
- 进入竖屏模式时把当前视频 hash 作为 `feedList[0]`，`feedIndex=0`。
- `loadNextVideo()`：取随机下一个（`GET /api/videos?sort=recommended&limit=8` 过滤当前后取首个），push 到 feedList，`feedIndex++`，加载该视频。
- `loadPrevVideo()`：若 `feedIndex>0` 则 `feedIndex--` 回到历史视频（不重新请求，记住）。
- 滑动方向由竖屏手势层 touchstart/touchmove/touchend 的 dy 判定（阈值 ~60px）。

### 双击点赞
- 竖屏手势层记录两次 tap 间隔 < 300ms 且位移小 → 触发 `handleLike()` + 爱心动画。

### 右侧操作栏（竖屏专属）
- 点赞（含已赞态高亮）、收藏（含已收藏态高亮）。
- 角落「不喜欢」按钮（左下角），点击 `handleDislike()`。
- 顶部/底部按钮区：「横屏全屏」(`toggleFullscreen`)、「详情」(路由跳 `/video/:hash` 不带 mode)、「退出竖屏」。

### 横屏全屏
- 竖屏内「横屏全屏」按钮：先退出竖屏视觉(`playMode='normal'`)再 `requestFullscreen()` 让原生播放器铺满。

### 详情模式
- 竖屏内「详情」按钮：路由 `router.push({ name:'Video', params:{hash}, query:{} })`，即当前普通详情页。

## 三、Todo List

- [x] 1. 方案文档（本文件）
- [x] 2. Video.vue：新增 playMode / feedList / feedIndex state 与初始化（路由 query 驱动）
- [x] 3. Video.vue：竖屏「全屏」按钮旁加「竖屏全屏」入口按钮（普通模式控制栏）
- [x] 4. Video.vue：竖屏模式模板（.portrait-mode 容器 + video + 右侧操作栏 + 角落不喜欢 + 顶部切换按钮）
- [x] 5. Video.vue：竖屏滑动手势（上/下切换视频，记住历史）+ 双击点赞
- [x] 6. Video.vue：loadNextVideo / loadPrevVideo（随机流 + 历史回退）
- [x] 7. Video.vue：竖屏内「横屏全屏」「详情」「退出」按钮逻辑
- [x] 8. Video.vue：竖屏模式 CSS（9:16 沉浸、右侧栏、动画）
- [x] 9. router：无需改（复用 /video/:hash?mode=portrait）
- [x] 10. 临时脚本截图验证（移动端 390px 视口）
- [x] 11. 清理临时文件 + git 提交（commit a02a26c）

## 四、数据流与接口复用

- 随机下一个：`videoApi.getVideos({ limit: 8, sort: 'recommended' })` 过滤当前 hash 取首个。
- 历史：`historyApi.getHistory()` 用于「上滑历史」兜底（主要用本地 feedList 记忆）。
- 互动：`videoApi.likeVideo / favoriteVideo / dislikeVideo` 已有，直接复用 handleLike/handleFavorite/handleDislike。
- 视频源：竖屏内 video 复用 `videoUrl` computed + token。

## 五、实现注意

- 竖屏模式视频与详情页视频共享 `videoPlayer` ref 不便（两处 <video>），竖屏用独立 `portraitPlayer` ref。
- 进入竖屏时自动 play；切换视频时重置 currentTime。
- 退出竖屏恢复详情页播放进度由现有逻辑处理。
- 竖屏模式不触发浏览器 fullscreenchange，isFullscreen 独立。
