# 多模式资源管理系统（Multi-Mode Resource Management）

> 状态：已评审，待实施
> 目标：让外部下载脚本在入库时**自主选择资源归属的模式**（视频 / 漫画 / 图文 / 文本 / 动态），
> 一套资源可同时出现在多个模式，也可只出现在某个组合模式（如"图文+视频一体的帖子"只在动态可见、不进视频列表）。
> 设计原则：**最彻底、零技术债务、架构最合理、可平滑扩展文本等未来模式**。

---

## 1. 核心抽象：两个正交维度

| 维度 | 含义 | 现状 | 本方案 |
|------|------|------|--------|
| **Library（资源库）** | 物理存储分组（不同磁盘/文件夹） | `ResourceLibrary`（resourced 路径注册表） | 不变，作为物理维度 |
| **Mode（模式）** | 逻辑呈现轴（视频/漫画/图文/文本/动态） | 隐式 = "实体是否存在" | **显式归属**，一等公民 |

**关键判断**：当前"某资源在哪个模式可见"完全由"是否建了 `Video`/`Comic` 实体"隐式决定。
这正是技术债务根源——无法表达"同一个视频文件只进动态、不进视频列表"，也无法让一个资源同时属于多个模式。

本方案把**模式归属**从实体存在性中解耦出来，引入显式归属层。

---

## 2. 数据模型

### 2.1 通用资产：`ResourceIndex`（已有，扩展 `kind`）
`src/web/core/models.py` 的 `ResourceIndex` 已是正确地基：
- `kind` 扩展取值：`video_file` / `comic_folder` / `text`（新增）/（未来 `image_set` 复用 `comic_folder`）。
- `meta`（JSON）升级为**通用呈现存储**，标准化键：
  - `title`, `thumbnail`, `duration`(视频秒), `width`, `height`,
    `page_count`(图文/漫画), `caption`(每资源备注), `source_url`, `downloaded_by`, `summary`(文本摘要)
- 新增 `presentation()` 方法，返回上述字段的规整字典（缺省兜底），供任何模式无差别渲染卡片。

### 2.2 模式归属表：`resource_memberships`（新增，单一真相源）
```python
class ResourceModeMembership(db.Model):
    __tablename__ = 'resource_memberships'
    id = Column(Integer, primary_key=True)
    resource_index_id = Column(Integer, ForeignKey('resource_index.id'), nullable=False, index=True)
    mode = Column(String(32), nullable=False, index=True)      # 'video'|'comic'|'text'
    position = Column(Integer, default=0)
    note = Column(Text)                                        # 该模式下覆盖的标题/说明
    collection_id = Column(Integer, ForeignKey('collections.id'), nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint('resource_index_id', 'mode', name='uq_res_mode'),)
```
- **单资源模式**（video/comic/text）的可见性 = 存在对应 `mode` 的归属行。
- 归属行与富化实体（见 2.3）在**同一事务**内写入，杜绝双源漂移。

### 2.3 模式富化实体（Enrichment，可选）
- `Video`（已有）：video 模式的富化层（标签/互动/播放进度等），由 `mode='video'` 归属驱动创建。
- `Comic`（已有）：comic 模式的富化层（分页图片），由 `mode='comic'` 归属驱动创建。
  - **"图文"需求**：图片即一个 `Comic`（comic_folder），被 Dynamic 引用即呈现为图文。无需新表。
- `Text`（新增，轻量）：text 模式的富化层。
  ```python
  class Text(db.Model):
      __tablename__ = 'texts'
      id = Column(Integer, primary_key=True)
      resource_index_id = Column(Integer, ForeignKey('resource_index.id'), nullable=False, unique=True)
      body = Column(Text)          # 正文（Markdown/纯文本）
      summary = Column(Text)
      resource_index = relationship('ResourceIndex', backref='text')
  ```

### 2.4 组合模式：Dynamic（已有，天然多模式）
- `Dynamic` + `DynamicRef` 已是组合模式：**一条动态可自由引用任意 `ResourceIndex`**。
- "图文+视频一体的帖子" = 一条 Dynamic 引用一个 `comic_folder`（图）+ 一个 `video_file`（视频）。
- 资源"在动态可见" = 被某条 Dynamic 通过 `DynamicRef` 引用（无需 membership 行，组合关系即归属）。
- `Dynamic.to_dict(resolve=True)` 解析引用时：若引用目标无 `Video`/`Comic` 实体（即只属于动态），**回退到 `ResourceIndex.presentation()`**，保证仍能渲染标题/缩略图/时长。

### 2.5 模式内分组：`collections`（新增，可选但完善）
```python
class Collection(db.Model):
    __tablename__ = 'collections'
    id = Column(Integer, primary_key=True)
    name = Column(String(128), nullable=False)
    mode = Column(String(32), nullable=False, index=True)
    library_id = Column(Integer, nullable=True)
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=utcnow)
```
入库可指定 `collection_id`，把资源归入某模式的某个合集（如"某次爬取的图文合集"）。

### 2.6 模式注册表（集中枚举）
`src/web/core/models.py` 新增：
```python
class ResourceMode:
    VIDEO = 'video'
    COMIC = 'comic'
    TEXT  = 'text'
    DYNAMIC = 'dynamic'   # 组合模式，不在 membership 表，由 DynamicRef 表达
    # 未来：IMAGE = 'image'
```

---

## 3. 入库管线（核心改动，解决用户场景）

`src/web/script_engine/ingest.py` 的 `ingest_file` 升级为 **`ingest_asset`**，签名：
```python
def ingest_asset(app, library_id, path, kind,
                 modes=('video',), collection_id=None, meta=None):
```
流程：
1. 解析/创建 `ResourceIndex`（按内容指纹去重，见既有 `generate_hash`）。
2. 将 `meta` 合并进 `ResourceIndex.meta`（标题、缩略图、时长等）。
3. 对每个 `mode`：
   - `video` → 确保 `Video` 行 + `membership(mode='video')`
   - `comic` → 确保 `Comic` 行 + `membership(mode='comic')`（扫描分页图片）
   - `text`  → 确保 `Text` 行 + `membership(mode='text')`
   - `dynamic` → **不建任何单资源实体**，仅返回 `resource_index_id` 供调用方建 Dynamic 引用
4. 返回 `{resource_index_id, modes, membership_ids}`。

**对应三个场景**：
- 只下视频 → `modes=['video']` → 建 `Video` → 视频列表可见。
- 图文+视频一体 → 得到 `comic_folder`+`video_file` 两个 `ResourceIndex`，脚本建一条 `Dynamic` 引用二者，`modes` 都不含 `video`（不建 `Video`）→ **视频列表不显示该视频，动态模式呈现完整图文+视频卡片**。
- 未来纯文本 → `kind='text'`, `modes=['text']` → 文本模式可见。

---

## 4. API 设计

### 4.1 资源池（统一查询，供动态引用选择器 / 未来各模式复用）
- `GET /api/resource-index?mode=video|comic|text&library_id=&search=` → 列出资源 + 归属模式 + `presentation()`
- `POST /api/resource-index/<id>/modes` `{modes:[...], collection_id?}` → 设置/更新归属（幂等）
- `POST /api/resource-index/<id>/repoint` `{location}`（已有，admin）

### 4.2 合集
- `GET /api/collections?mode=` / `POST /api/collections` `{name,mode,library_id}`

### 4.3 文本模式（最小可用）
- `GET /api/texts?library_id=&search=` → 列表（基于 membership mode='text'）
- `POST /api/texts` `{resource_index_id, body, summary}` / `PUT/DELETE /api/texts/<id>`

### 4.4 动态（已有，增强）
- 引用解析回退 `presentation()`（见 2.4）。
- 新建动态时引用选择器改为调用 `GET /api/resource-index`（跨模式选资源）。

### 4.5 视频列表（保持兼容）
- `GET /api/videos` **保持不变**（Video 实体存在即 video 模式，性能最优、不动播放器）。
- 通过"建 Video 必写 membership"的事务约束，使 `resource_memberships` 始终与实体一致，
  作为跨模式统一查询的权威注册表；`/api/videos` 是 video 模式的专用高性能读路径。
  （注：此为刻意保留的性能桥接，非双源债务——写入由同一事务保证一致。）

---

## 5. 前端集成

- `src/webui/src/types/index.ts`：新增 `ResourceIndex`、`ResourceModeMembership`、`Collection`、`Text` 类型。
- `src/webui/src/api/index.ts`：新增 `resourceApi`（资源池/归属/合集）、`textApi`。
- `Home.vue`：媒体 tab 由写死的 `video|comic|mixed` 改为从 `GET /api/modes`（返回可用模式）动态渲染；
  新增"文本"tab（`?mode=text`）渲染 `Texts.vue`。
- `Dynamics.vue`：引用选择器改用 `resourceApi.pool()`（跨模式选视频/图文/文本）。
- 脚本运行 UI（`AdminScripts.vue`）：解析 manifest 的 `target_modes`（`multi_enum` 类型，manager 已支持校验），
  渲染为多选模式；运行结果回传 `modes` 给 `ingest_asset`。
- `Texts.vue`（新增，最小）：文本列表 + 查看/新建（调用 textApi）。
- manifest 示例（某插件 `extensions/<plugin_id>/manifest.json`）：新增
  ```json
  {"key":"target_modes","label":"入库模式","type":"multi_enum",
   "options":["video","comic","text","dynamic"],"default":["video"]}
  ```

---

## 6. 数据迁移（清债，幂等）
扩展 `migrate_resource_index()`：
1. 为 `videos`/`comics` 已存在的行**补写** `resource_memberships`（mode 对应）。
2. 新建 `texts`/`collections`/`resource_memberships` 表（通过 `db.create_all()` + 幂等 ALTER）。
3. 将既有视频时长/标题等规整进 `ResourceIndex.meta`（若为空），使 `presentation()` 对老数据也成立。
启动日志打印 `[MIGRATE] mode-memberships 回填完成 (video=N, comic=M)`。

---

## 7. 外部脚本接入示例
```python
# 在脚本 run.py 中：通过 notify 上报每个文件及其目标模式
yield {"type":"file","path":video_path,"target_modes":["dynamic"]}   # 只进动态
yield {"type":"file","path":img_folder,"target_modes":["dynamic"]}   # 图文一起进动态
yield {"type":"file","path":solo_video,"target_modes":["video"]}     # 只进视频
```
管理器在 `_reconcile` 中将 `target_modes` 透传给 `ingest_asset`。

---

## 8. 分阶段执行清单 & 验收

**P1 后端地基**
- [ ] models：ResourceMode 枚举、ResourceModeMembership、Collection、Text、`ResourceIndex.presentation()`
- [ ] migrate 扩展（补 membership + meta 规整）
- [ ] ingest_asset（modes 感知）
- [ ] 资源池 / 合集 / 文本 API
- [ ] Dynamic.to_dict 解析回退 presentation()
- [ ] 启动验证 + 回归 `/api/videos`

**P2 脚本与前端**
- [ ] manager 透传 target_modes；manifest 加 target_modes
- [ ] types/api 新增
- [ ] Home 动态 tab、Dynamics 引用选择器接资源池
- [ ] Texts.vue + 文本 tab
- [ ] AdminScripts 渲染 target_modes

**P3 验证（playwright）**
- [ ] 只下视频 → 视频列表可见、动态不可见
- [ ] 图文+视频一体 → 视频列表不可见、动态可见完整卡片
- [ ] 文本模式最小可用
- [ ] 旧数据回归（视频/漫画数量不变）

> 文档即架构契约；实施严格对齐本文件，避免增量补丁式 debt。
