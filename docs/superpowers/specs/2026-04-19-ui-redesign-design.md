# PaddleOCR UI 重构设计

## 目标

将现有简单任务列表界面重构为专业级文档 OCR 工作台，支持多文件拖拽上传、原文件与识别结果并排对比、文件管理和后台管理。

## 技术栈

- 前端：Vue 3 + Element Plus + Pinia + markdown-it + pdfjs-dist
- 后端：FastAPI + SQLAlchemy async + WebSocket
- 构建：Vite

## 整体布局

顶部导航栏（Logo + 用户信息 + 登出按钮），下方 3 个 Tab 页签：

- **上传任务** — 主工作区
- **文件管理** — 文件浏览与下载
- **管理后台** — 仅管理员可见

### Tab 1：上传任务（主工作区）

左右分栏布局，各占 50% 宽度。

**左列：**

| 区域 | 内容 |
|------|------|
| 上方 — 上传区域 | Element Plus `el-upload` 拖拽模式，accept 限定文件类型，多文件选择，单文件上限 1GB，文件列表显示名称+大小+状态，「开始转换」按钮 |
| 下方 — 原文件预览 | PDF 用 pdfjs-dist 渲染，图片直接 img 标签。点击右侧队列文件时左侧同步显示对应原文件 |

**右列：**

| 区域 | 内容 |
|------|------|
| 上方 — 转换队列 | 文件卡片列表：文件名、大小、状态（排队中/处理中/已完成/失败）、进度百分比。WebSocket 实时更新。完成卡片可点击触发预览 |
| 下方 — Markdown 预览 | markdown-it 渲染，顶部工具栏：Markdown/纯文本切换、复制、下载（MD/TXT） |

左右下方并排：左边原文件，右边识别结果，方便对比校对。

### Tab 2：文件管理

Element Plus `el-table` 展示文件列表：

- 列：文件名、文件类型、上传时间、状态、操作
- 普通用户：后端按 user_id 过滤，只看自己文件
- 管理员：看全部文件，额外显示上传者列
- 分页 + 按文件名搜索 + 按状态筛选
- 批量勾选支持

操作按钮：

- 下载：下拉选择格式（MD / TXT / DOCX）
- 批量勾选后顶部出现「打包下载 ZIP」按钮
- 删除：二次确认弹窗

### Tab 3：管理后台（仅管理员）

前端路由守卫检查 `is_admin`，非管理员隐藏此 Tab。

**用户管理：**

- 用户列表表格：用户名、显示名、角色、创建时间、操作
- 操作：修改角色（管理员/普通用户）、禁用/启用

**API Key 管理：**

- 创建 Key（输入名称）
- Key 列表（显示前 8 位 + 掩码）
- 吊销 Key
- 已有后端接口 `/auth/api-keys`，前端对接

**系统配置（预留）：**

- OCR 并发数、超时时间
- 当前为环境变量配置，后续可改为数据库存储

## 后端 API 变更

### 新增接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/files` | 文件列表（分页、筛选、管理员看全部） |
| GET | `/api/v1/files/{id}/download?format=md\|txt\|docx` | 单文件下载 |
| POST | `/api/v1/files/batch-download` | 批量打包 ZIP 下载 |
| DELETE | `/api/v1/files/{id}` | 删除文件及结果 |
| PUT | `/api/v1/admin/users/{id}` | 修改用户角色/状态 |
| GET | `/api/v1/admin/users` | 用户列表（管理员） |

### 修改接口

- `POST /api/v1/tasks` — 上传文件大小限制改为 1GB
- `GET /api/v1/tasks` — 管理员返回全部任务，普通用户返回自己的

### 认证与权限

- Cookie（Session）认证 + API Key 认证双模式保持不变
- 管理员 API 增加 `require_admin` 依赖注入
- 文件管理 API 根据当前用户 `is_admin` 决定查询范围

## 前端组件结构

```
frontend/src/
├── views/
│   ├── MainView.vue          # 主布局（Tab 容器）
│   ├── TaskWorkspace.vue     # Tab1: 上传任务（左右分栏）
│   ├── FileManagement.vue    # Tab2: 文件管理
│   └── AdminPanel.vue        # Tab3: 管理后台
├── components/
│   ├── UploadArea.vue        # 拖拽上传区域
│   ├── FilePreview.vue       # 原文件预览（PDF/图片）
│   ├── TaskQueue.vue         # 转换队列（文件卡片列表）
│   ├── MarkdownPreview.vue   # Markdown 结果预览
│   ├── FileTable.vue         # 文件列表表格
│   └── AdminUserTable.vue    # 用户管理表格
├── stores/
│   ├── task.js               # 任务状态（队列、进度、预览）
│   ├── file.js               # 文件管理状态
│   └── user.js               # 用户信息（含 is_admin）
└── router/
    └── index.js              # 路由守卫：检查登录、检查管理员
```

## 文件大小限制

- 前端：`el-upload` beforeUpload 钩子检查文件大小，1GB 上限
- 后端：FastAPI 请求体大小限制改为 1GB（`--limit-max-request-size` 或中间件）
- Nginx（如有）：`client_max_body_size 1G`

## 输出格式

- MD：默认，直接返回 OCR 结果 Markdown 文本
- TXT：去除 Markdown 格式标记的纯文本
- DOCX：使用 python-docx 将 Markdown 转换为 Word 文档
- ZIP：使用 Python zipfile 将多个结果打包

## WebSocket 进度

- 已有 `ws_router.py`，需与 `task_engine.py` 联动
- 任务状态变更时通过 WebSocket 推送：task_id、status、progress、result
- 前端使用原生 WebSocket 或 `@vueuse/core` 的 `useWebSocket` 连接

## 错误处理

- 上传失败：显示具体错误信息（文件过大、类型不支持、网络错误）
- OCR 失败：队列卡片标红，显示错误原因，支持重试
- 下载失败：Toast 提示
- 管理操作失败：Message 提示具体原因
