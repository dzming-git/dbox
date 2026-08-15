# 竖屏模式跟手滑动（抖音/B站式 feed track）重构方案

> 目标：把"滑动判定后原地替换视频"改为"手指拖动时整条视频轨道跟手上下平移，松手按位移吸附切换"，体验对标抖音/B站。

## 现状问题
当前 `Video.vue` 竖屏模式是单视频 + 手势层：松手超过阈值直接 `loadNext/loadPrev` 替换 `portraitVideo`，表现为"划完原地刷新、视频不跟手"。

## 目标交互
- 手指按住上下拖动 → 当前视频跟手平移，上下露出相邻视频（层次感）
- 松手：位移 > 阈值 → 吸附到相邻视频并播放；否则回弹原位
- 上滑 = 下一个（随机未看过，追加 feedList 记住历史）；下滑 = 上一个（回退历史）
- 双击点赞、点赞/收藏/不喜欢、横屏/详情入口、不喜欢位置、防底层下拉刷新均保持

## 实现要点
1. **轨道结构**：`.portrait-track`（height:300%，含 3 个 `.portrait-item` 各 100% 视口高），
   依次渲染 prev / current / next。current 始终居中（track translateY = -100% * 1 + dragY）。
2. **跟手**：`touchmove` 实时 `portraitDragY = dy`，关闭 transition；`touchend` 开 transition 吸附。
3. **相邻预览**：拖动时 prev/next item 显示相邻视频的封面/标题占位（从缓存的预览对象读取），切换后才真正加载视频 URL 并 play。
4. **数据**：维护 `feedList`(hash 序列) + `feedIndex`(当前)。新增 `portraitNeighbors` 缓存 prev/next 的预览信息（hash/title/cover）。
5. **手势层**：移到 `.portrait-track` 上统一监听 touch，避免与按钮/视频点击冲突（按钮用 `@click.stop`）。

## Todolist
- [x] 1. state：新增 portraitDragY / portraitDragging / portraitTransition / portraitNeighbors
- [x] 2. 模板：`.portrait-track` 包裹 prev/current/next 三个 `.portrait-item`，手势监听在 track
- [x] 3. 手势：touchmove 实时设 dragY（跟手，关 transition）；touchend 按阈值吸附（开 transition）
- [x] 4. 切换：吸附完成后更新 feedIndex + 加载相邻视频并 play，dragY 归零（无动画瞬时归位）
- [x] 5. 相邻预览：拖动时 prev/next item 展示封面/标题占位
- [x] 6. CSS：track height/translateY/transition，item 100% 视口，cover 占位层
- [x] 7. 保留：双击点赞、操作栏、不喜欢、横屏/详情、防底层刷新
- [ ] 8. 验证：Playwright 模拟 touch 拖动确认跟手 + 吸附切换
