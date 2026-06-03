# Web 前端 UI 设计文档

## 概述

为 AI 动漫图片生成项目构建完整的 Web 前端界面，替代现有 CLI 操作方式。

- **目标**：完全替代 CLI，所有操作在浏览器中完成
- **技术栈**：FastAPI (后端) + Vue 3 + Vite (前端)
- **架构模式**：前后端分离开发，Vite 代理 API 请求到 FastAPI

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    Browser (Vue 3 + Vite)                │
│  GenerateView  HistoryView  PreferencesView  CompareView │
│       │              │              │            │       │
│       └──────────────┴──────────────┴────────────┘       │
│                        │  fetch + EventSource            │
└────────────────────────┼────────────────────────────────┘
                         │  HTTP :8000
┌────────────────────────┼────────────────────────────────┐
│              FastAPI Server (:8000)                       │
│                                                          │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │  REST Endpoints   │  │  SSE Streams       │            │
│  │  POST /generate   │  │  GET /events/{id}  │            │
│  │  GET  /tasks      │  │                    │            │
│  │  POST /interact   │  │  场景扩写 ✓         │            │
│  │  GET  /prefs      │  │  提示词生成 ✓       │            │
│  └────────┬─────────┘  │  3D 场景渲染 ✓      │            │
│           │             │  AI 图像生成 ✓      │            │
│           │             │  高分辨率修复 ✓     │            │
│           │             └──────────┬─────────┘            │
│           │                        │                      │
│  ┌────────┴────────────────────────┴──────────┐          │
│  │           LangGraph Pipeline                 │          │
│  │  text_expander → coder → blender → sdxl      │          │
│  │  (worker.py 包装 astream → emit 事件)        │          │
│  └─────────────────────────────────────────────┘          │
│                                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐           │
│  │ DeepSeek  │  │ Blender  │  │   ComfyUI     │           │
│  │   API     │  │ subprocess│  │   HTTP API    │           │
│  └──────────┘  └──────────┘  └──────────────┘           │
└──────────────────────────────────────────────────────────┘
```

### 关键设计决策

| 决策 | 选择 | 原因 |
|------|------|------|
| 实时通信 | SSE + REST | 单向推送足够，浏览器原生 EventSource 自动重连 |
| LangGraph 改造 | asyncio.Queue 事件 | 最小侵入，每个节点 emit dict |
| 前后端通信 | Vite proxy → FastAPI | 开发时不跨域 |
| 图片服务 | FastAPI 静态文件挂载 output/ | 零额外配置 |
| 状态管理 | Pinia store (task + prefs) | Vue 3 官方推荐 |
| 存储 | JSON 文件 | 零依赖，轻量（history.json + user_prefs.json） |
| ComfyUI | FastAPI 自动拉起 subprocess | 启动时 Popen，关闭时 terminate；TheFooter 显示连接状态 |

## 项目目录结构

```
PJ3/
├── agents/              # 现有 — 不改
├── graph/               # 现有 — 不改
├── state/               # 现有 — 不改
├── utils/               # 现有 — 不改
├── config.py            # 现有 — 加几个 key
├── main.py              # 现有 — 保留 CLI 入口
├── server/              # ★ 新增 (FastAPI)
│   ├── __init__.py
│   ├── app.py           # FastAPI 应用工厂 + CORS + 静态文件
│   ├── routes.py        # REST + SSE 端点
│   └── worker.py        # LangGraph 管线包装 + 事件 emit
├── web/                 # ★ 新增 (Vue 3 + Vite)
│   ├── src/
│   │   ├── main.js
│   │   ├── App.vue
│   │   ├── router.js
│   │   ├── views/
│   │   │   ├── GenerateView.vue
│   │   │   ├── HistoryView.vue
│   │   │   ├── HistoryDetail.vue
│   │   │   ├── PreferencesView.vue
│   │   │   └── CompareView.vue
│   │   ├── components/
│   │   │   ├── TheNav.vue
│   │   │   ├── TheFooter.vue
│   │   │   ├── PromptInput.vue
│   │   │   ├── ProgressPanel.vue
│   │   │   ├── ResultDisplay.vue
│   │   │   ├── InteractiveMenu.vue
│   │   │   ├── ImageLightbox.vue
│   │   │   ├── ToastNotification.vue
│   │   │   ├── SearchBar.vue
│   │   │   ├── HistoryGrid.vue
│   │   │   ├── HistoryCard.vue
│   │   │   ├── PreferenceCategory.vue
│   │   │   ├── TagEditor.vue
│   │   │   ├── ImageSlot.vue
│   │   │   └── CompareControls.vue
│   │   ├── stores/
│   │   │   ├── taskStore.js
│   │   │   └── prefsStore.js
│   │   └── api/
│   │       ├── client.js       # fetch 封装
│   │       └── sse.js          # SSE EventSource 封装
│   ├── index.html
│   ├── vite.config.js
│   └── package.json
└── output/              # 现有 — 图片输出
```

## 前端设计

### 路由结构

```
/                GenerateView    默认主页：输入 → 进度 → 结果 → 菜单
/history         HistoryView     历史画廊：浏览/搜索
/history/:id     HistoryDetail   单张详情：大图 + 元数据 + 参数
/preferences     PreferencesView 偏好管理：6 维度标签编辑
/compare         CompareView     多图对比：选 2-4 张并排
```

### 页面 1：生成页 (GenerateView)

整个用户流程在一页内完成：

**布局**：顶部输入栏 → 左侧进度面板 + 右侧结果展示区 → 底部交互菜单

**组件树**：
```
GenerateView.vue
├── PromptInput.vue          — 文本输入框 + 预设风格按钮
├── ProgressPanel.vue        — 5 节点进度条 (SSE 驱动)
│   └── 节点友好名: 场景扩写 | 提示词生成 | 3D 场景渲染 | AI 图像生成 | 高分辨率修复
├── ResultDisplay.vue        — 大图展示 + 缩放/下载
└── InteractiveMenu.vue      — 6 选项菜单 + 描述输入
```

**交互流程**：
1. 用户输入场景描述 → 点击"开始生成"
2. SSE 实时推送进度：场景扩写 → 提示词生成 → 3D 场景渲染 → AI 图像生成（多 seed 网格图）→ 高分辨率修复
3. 生成完成 → 底部显示 6 选项菜单：
   [1] ✅ 满意保存  [2] ☀️ 换光线  [3] 🎨 换场景
   [4] ✏️ 微调角色  [5] 🔄 换姿态  [6] 🖼️ 换风格
4. 用户选择调整类别 + 输入描述 → 仅重跑 SDXL + Hires Fix → 循环直到满意
5. 点击满意保存 → 持久化偏好 + 保存历史

### 页面 2：历史画廊 (HistoryView)

- 缩略图网格布局 (4 列)
- 搜索栏：按提示词关键词搜索 + 日期范围筛选
- 点击卡片 → HistoryDetail：大图 + 完整提示词 + 生成参数

**组件树**：
```
HistoryView.vue
├── SearchBar.vue
├── HistoryGrid.vue
│   └── HistoryCard.vue
└── HistoryDetail.vue (路由 /history/:id)
```

### 页面 3：偏好管理 (PreferencesView)

- 6 个审美维度卡片，每卡片显示当前喜欢的标签
- 支持手动添加/删除标签
- "重置偏好"按钮清空所有数据

### 页面 4：多图对比 (CompareView)

- 从历史中选择 2-4 张图片，并排对比
- 每格显示：图片 + 提示词标签 + 生成参数

### 全局组件

| 组件 | 说明 |
|------|------|
| TheNav.vue | 顶部导航 (Generate / History / Preferences / Compare) |
| TheFooter.vue | 底部状态栏 (ComfyUI ● 在线 / Blender ✓) |
| ImageLightbox.vue | 点击图片全屏放大 + 滚轮缩放 |
| ToastNotification.vue | SSE 事件驱动的通知 (成功/失败/进度) |

## 后端设计

### REST API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/generate` | 提交生成任务 → 返回 task_id |
| `GET` | `/api/events/{task_id}` | SSE 事件流 |
| `POST` | `/api/tasks/{task_id}/interact` | 交互菜单：改光线/场景/角色/姿态/风格 |
| `POST` | `/api/tasks/{task_id}/done` | 用户确认满意 → 持久化偏好 + 保存历史 |
| `GET` | `/api/tasks` | 历史列表 (?search=&page=&limit=) |
| `GET` | `/api/tasks/{task_id}` | 单条任务详情 |
| `GET` | `/api/preferences` | 获取当前偏好 |
| `POST` | `/api/preferences` | 更新偏好标签 |
| `DELETE` | `/api/preferences` | 重置所有偏好 |
| `GET` | `/api/status` | 系统状态：ComfyUI (含自动启动状态) / Blender |

### SSE 事件流

```
event: progress → {"node":"场景扩写","status":"running","progress":0}
event: progress → {"node":"场景扩写","status":"done","progress":25,"elapsed_ms":12000,"preview":"..."}
event: progress → {"node":"提示词生成","status":"running","progress":25}
event: progress → {"node":"提示词生成","status":"done","progress":50,"elapsed_ms":8000,"preview":"1girl,..."}
event: progress → {"node":"3D 场景渲染","status":"running","progress":50}
event: progress → {"node":"3D 场景渲染","status":"done","progress":75,"elapsed_ms":35000,"preview_url":"..."}
event: progress → {"node":"AI 图像生成","status":"running","progress":75}
event: grid      → {"image_urls":[...],"grid_url":"..."}
event: progress → {"node":"高分辨率修复","status":"running","progress":90}
event: progress → {"node":"高分辨率修复","status":"done","progress":100}
event: interactive → {"type":"menu","message":"图片生成完成！","image_url":"..."}
event: complete  → {"task_id":"...","image_url":"...","metadata":{...}}
```

### POST /api/tasks/{task_id}/interact

```json
{
  "action": "lighting",               // lighting | scene | character | pose | style
  "description": "金色的夕阳暖光"      // 用户自然语言描述
}
```

流程：LLM 改写 Danbooru prompt → 仅重跑 SDXL + Hires Fix（复用 Blender 深度图）→ 新 SSE 事件流 → 再次弹交互菜单

### 数据模型

```python
class Task:
    id: str                        # UUID
    user_input: str                # 用户原始输入
    status: str                    # pending | running | waiting_user | done | error
    created_at: datetime

    # 各节点输出
    expanded_text: Optional[str]
    sdxl_prompt: Optional[str]
    sdxl_negative_prompt: Optional[str]
    blender_script: Optional[str]
    depth_image_url: Optional[str]
    frame_image_url: Optional[str]
    final_image_urls: list[str]    # 最终大图 URL
    grid_image_url: Optional[str]  # 多 seed 网格图
    selected_seed: Optional[int]   # 用户选的变体

    # 交互历史
    interactions: list[dict]       # [{action, description, new_prompt}, ...]
    version: int                   # 交互版本号 (初始=1)

    # 参数快照
    params: dict                   # sampler, steps, cfg, seed, ...

    error_message: Optional[str]
```

### 存储方案

| 数据 | 位置 | 说明 |
|------|------|------|
| 任务历史 | `output/history.json` | JSON 数组，最多 200 条 |
| 用户偏好 | `user_prefs.json` | 现有 PreferenceManager |
| 生成图片 | `output/comfyui/` `output/blender/` | 现有不变 |
| 历史缩略图 | `output/thumbnails/` | Pillow 缩放到 300px 宽 |

## 管线改造

### worker.py — 包装 LangGraph + 事件发射

最小侵入模式：在 `server/worker.py` 中调用 `app.astream()`，每个节点完成后 push 事件到 `asyncio.Queue`。

```
async def run_pipeline(user_input: str, event_queue: asyncio.Queue):
    state = WorkflowState(user_input=user_input)
    async for step in app.astream(initial_state):
        node_name = list(step.keys())[0]
        # 根据 node_name 映射友好名 + emit 对应事件
        ...
```

对现有 agents/ 和 graph/ 目录 **零改动**。交互重生成时直接调用 `sdxl_enhancer` 中的 `_run_single_pass` 和 `_run_hires_pass`（需要将它们重构为可独立调用）。

### 交互重生成

`POST /interact` 的处理流程：
1. 从 Task 中获取当前 prompt + depth_path
2. 调用 LLM 改写 prompt（复用 `_rewrite_prompt` 逻辑）
3. 仅执行 SDXL 生成（不重跑 Blender）
4. 推送新的 progress + grid + interactive 事件

## 实施计划

### 阶段 1：后端骨架
- FastAPI app 工厂 + CORS
- Task 数据模型 (Pydantic)
- `output/history.json` 读写
- `POST /generate` + `GET /events/{id}` (SSE)
- `server/worker.py` — 包装 LangGraph astream + 事件发射
- 其他 REST 端点 (tasks, preferences, status)

### 阶段 2：前端核心
- Vue 3 脚手架 + Vite 配置 + 代理
- Pinia stores (task + prefs)
- SSE EventSource 封装
- GenerateView 完整流程：输入 → 进度 → 结果 → 交互菜单
- 基础样式系统 (CSS 变量 + 暗色主题)

### 阶段 3：辅助页面
- HistoryView + HistoryDetail
- PreferencesView (6 维度标签编辑)
- CompareView (2-4 张并排对比)
- ImageLightbox (全屏放大 + 滚轮缩放)
- TheFooter 系统状态栏
