# PaddleOCR API 说明文档

本文档说明 PaddleOCR Web UI 的 HTTP API，重点说明 **PDF → DOCX** 的分流规则：图片型 PDF 继续走 OCR 重建，非图片型 PDF 使用 exactdoc 直接转换以保留原版式、图片、页眉页脚和活动页码。

- 服务地址：**`http://192.168.0.8:5553/`**（固定）
- 认证方式：`X-API-Key` 请求头，或浏览器 Cookie 会话
- 所有接口返回 JSON，文件下载接口返回二进制流
- Web 界面顶栏「API 说明」页提供同样的调用示例（含 DWG/DXF）

---

## 1. 认证

### API Key

```http
X-API-Key: ak_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

### 获取 API Key

1. 使用管理员账号登录 `http://192.168.0.8:5553/`
2. 进入「管理后台」→「API Key 管理」→「新建 API Key」
3. 复制生成的 `ak_...`，请求时放在 `X-API-Key` 请求头

也可以用 Cookie 会话调用 `POST /auth/api-keys` 创建。文档中的 `ak_xxx`、`ak_xxxxxxxx` 都是占位符，请替换为真实 Key，不要泄露给他人。

使用 API Key 提交的任务优先级为 `1`，完成后 30 秒自动清理文件和数据库记录，请及时下载结果。

> ⚠️ **传输安全**：当前服务为内网 HTTP（`http://192.168.0.8:5553/`），API Key 会以明文传输，仅限可信内网使用。跨网/公网访问请部署 HTTPS 反向代理。

### Cookie 会话

通过 OOS SSO 登录后，浏览器携带 `paddleocr_session` Cookie。Web 界面使用该方式。

---

## 2. 提交识别任务

```http
POST /api/v1/tasks
Content-Type: multipart/form-data
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `file` | file | 是 | 待识别文件，最大 1GB |
| `task_type` | string | 否 | 固定 `ocr` |
| `output_formats` | string(JSON) | 否 | 输出格式数组，默认 `["markdown"]` |
| `engine` | string | 否 | `mineru`（默认）/ `vl16` / `ppocrv6` |
| `high_precision` | string | 否 | `"true"` / `"false"`，仅 `vl16` 生效 |
| `merge_pdf` | string | 否 | DWG→PDF 多页合并，默认 `"false"` |

支持的输出格式：`markdown`、`json`、`txt`、`docx`、`dwg`。

- DWG/DXF 输入：`dwg` 表示“仅转换 PDF（保留 DXF）”，不做 OCR
- PDF 输入：`dwg` 表示 PDF→DWG 转换

### 示例：PDF 转 DOCX

```bash
curl -X POST http://192.168.0.8:5553/api/v1/tasks \
  -H "X-API-Key: ak_xxxxxxxx" \
  -F "file=@招标文件.pdf" \
  -F 'output_formats=["docx"]' \
  -F "engine=mineru"
```

返回：

```json
{
  "task_id": 8171,
  "message": "任务已提交"
}
```

---

## 2.1 DWG / DXF 图纸

DWG/DXF 会先经 ACADxPDF 服务转 **PDF + DXF**：

- PDF 走识别引擎
- DXF 文字直接提取（vl16 路径），无需 OCR

### DWG → PDF + OCR（Markdown / JSON）

```bash
curl -X POST http://192.168.0.8:5553/api/v1/tasks \
  -H "X-API-Key: ak_xxx" \
  -F "file=@drawing.dwg" \
  -F 'output_formats=["markdown","json"]' \
  -F "merge_pdf=true"
```

### DWG / DXF 仅转 PDF（保留 DXF，不做 OCR）

```bash
curl -X POST http://192.168.0.8:5553/api/v1/tasks \
  -H "X-API-Key: ak_xxx" \
  -F "file=@drawing.dwg" \
  -F 'output_formats=["dwg"]'
```

> 对 DWG/DXF 输入，`dwg` 是“仅转换 PDF”的标记，不会生成 DWG 文件。

### PDF → DWG

```bash
curl -X POST http://192.168.0.8:5553/api/v1/tasks \
  -H "X-API-Key: ak_xxx" \
  -F "file=@drawing.pdf" \
  -F 'output_formats=["dwg"]'
```

### DXF 文字直接提取

```bash
curl -X POST http://192.168.0.8:5553/api/v1/tasks \
  -H "X-API-Key: ak_xxx" \
  -F "file=@drawing.dxf" \
  -F 'output_formats=["markdown","json","txt"]'
```

说明：

- `merge_pdf=true` 合并 DWG 多页 PDF；默认 `false`（按图框分页）
- 结果 ZIP 包含转换后的 PDF、DXF 和 Markdown/JSON 等结果文件
- DXF 文字直接提取在 `vl16` 路径生效；`mineru`/`ppocrv6` 会把转换后的 PDF 送对应引擎
- ACADxPDF 不可用时回退本地 `cad2x`（仅单页 PDF）

## 3. PDF → DOCX 分流规则

提交 PDF 且 `output_formats` 包含 `docx` 时，服务端先检测 PDF 是否含有可提取的文本层：

| PDF 类型 | 判定 | DOCX 生成方式 |
|---|---|---|
| **图片型 PDF**（扫描件、页面是图片） | 前 5 页提取不到有效文本 | 走现有 OCR 链路：`PDF → 引擎解析 → Markdown → ExportService.md_to_docx → DOCX` |
| **非图片型 PDF**（有文本层） | 前 5 页能提取到文本 | 走 exactdoc 直转：`PDF → exactdoc（refine 3）→ DOCX` |

### 非图片型 PDF（exactdoc）

#### docx-only 快速路径

当 `output_formats` 恰好为 `["docx"]` 且 PDF 有文本层时，任务直接调用 exactdoc，**跳过 OCR 引擎**。这种情况下：

- `result.docx` 为 exactdoc 直转产物
- `result.md` 由 DOCX 提取纯文本生成，**仅用于页面预览**，不是 OCR 结果
- 任务耗时主要是 exactdoc 转换时间

如果同时请求了 `markdown` / `json` / `txt`，服务端仍会运行所选引擎生成这些格式，DOCX 再使用 exactdoc 直转。

- 使用 **exactdoc 0.3.0b3**（Apache-2.0）直接解析 PDF 并重建 DOCX
- 默认 `--refine 3`：用 LibreOffice 渲染 DOCX，逐页修正溢出和偏移
- 保留：
  - 原版式（字体、字号、位置、分栏、表格）
  - 图片、图形（矢量图会栅格化）
  - 页眉、页脚（写入 Word 原生 header/footer）
  - 活动页码（`PAGE` / `NUMPAGES` 域）
- 中文基本保持可编辑；在测试的 195 页招标文件上，中文字符覆盖率约 99%

### 图片型 PDF（现有 OCR 链路）

- 由所选引擎（`mineru` / `vl16` / `ppocrv6`）解析
- 结果先写入 `result.md`，再按需导出 `docx`
- DOCX 是 OCR 文字重建，不保留原版式

### Office 文档（DOCX / DOC）

Office 文档在 `output_formats` 只包含 `docx` / `markdown` 时走快速路径，不调用 OCR 引擎：

| 输入 | 输出 | 实现 |
|---|---|---|
| `.docx` | `docx` | 直接复制原文件为 `result.docx` |
| `.doc` | `docx` | LibreOffice 直接转 DOCX |
| `.docx` | `markdown` | Pandoc 直转 GFM |
| `.doc` | `markdown` | LibreOffice 转 DOCX → Pandoc |
| `.docx`/`.doc` | `docx` + `markdown` | 同时生成 DOCX 和 Markdown |

- DOCX→Markdown 保留标题、列表、表格；图片内联为 data URI
- 混合其他格式（如 `json`/`txt`）时，仍由所选引擎处理这些格式
- 快速路径失败时自动回退到原有 OCR 流程

### 回退机制

以下情况 exactdoc 会回退到 `Markdown → DOCX`，任务不会失败：

- exactdoc 未安装或命令执行失败
- 转换超时（`PDF_DOCX_TIMEOUT`）
- PDF 页数超过 `PDF_DOCX_MAX_PAGES`
- 加密、可填写表单等 exactdoc 拒绝的 PDF

回退后会记录 `WARNING` 日志，任务结果中仍是有效的 DOCX。

---

## 4. 查询任务

```http
GET /api/v1/tasks/{task_id}
```

返回任务状态、进度和结果：

```json
{
  "task": {
    "id": 8171,
    "status": "completed",
    "engine": "mineru",
    "progress": 100,
    "page_total": 195,
    "processing_time": 245,
    "error_message": null
  },
  "result": "# Markdown 结果...",
  "result_json": "{...}",
  "ppocr_data": null
}
```

任务状态：`pending` / `queued` / `processing` / `completed` / `failed` / `cancelled`。

取消任务：

```http
DELETE /api/v1/tasks/{task_id}
```

仅 `pending` / `queued` 状态可取消。

---

## 5. 下载结果

| 接口 | 说明 |
|---|---|
| `GET /api/v1/files/{id}/download?format=docx` | 下载 DOCX |
| `GET /api/v1/files/{id}/download?format=txt` | 下载纯文本 |
| `GET /api/v1/files/{id}/download?format=json` | 下载 JSON |
| `GET /api/v1/files/{id}/download?format=md` | 下载整目录 ZIP（与 `zip` 相同） |
| `GET /api/v1/files/{id}/download?format=zip` | 下载整目录 ZIP |
| `POST /api/v1/files/batch-download` | 批量打包结果目录 |

### 关于 `format=docx`

下载接口**优先返回任务处理时保存的 `result.docx`**：

- 非图片型 PDF 走 exactdoc 直转时，`result.docx` 就是 exactdoc 产物，下载接口直接返回它
- 图片型 PDF 或混合格式任务，`result.docx` 是 OCR/Markdown 生成的结果，同样直接返回
- 如果任务提交时未勾选 `docx`，结果目录没有 `result.docx`，接口才从 `result.md` 现场生成

整目录 ZIP 始终包含 `result.docx`（如果存在）。

---

## 5.1 文档转换专用 API

除异步任务 API 外，提供两个专用转换接口，适合「直接把文档转成 Markdown / DOCX」的场景。

### POST /api/v1/convert/markdown

认证：`X-API-Key` 或浏览器 Cookie。

| 表单字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | `.docx` / `.doc` / `.pdf` |
| `engine` | 否 | 仅 PDF 生效：`mineru`（默认）/ `vl16` / `ppocrv6` |

**DOCX / DOC：同步返回 Markdown**

```json
{
  "markdown": "# 标题\n\n正文...",
  "format": "docx",
  "engine": "pandoc",
  "chars": 12345,
  "filename": "报告.docx"
}
```

- DOCX 用 Pandoc 转 GFM，保留标题、列表、表格
- 图片会内联为 `data:image/...;base64,...`，Markdown 自包含
- DOC 先用 LibreOffice 转 DOCX，再走 Pandoc
- 不走 OCR，不创建任务记录
- 同步转换最多 **2 个并发**；Pandoc 超时 `OFFICE_MARKDOWN_TIMEOUT`（默认 300s）
- 图片内联限制：单张 20MB、总量 50MB，超出会跳过该图片

```bash
curl -X POST http://192.168.0.8:5553/api/v1/convert/markdown \
  -H "X-API-Key: ak_xxx" \
  -F "file=@报告.docx"
```

**PDF：创建异步任务**

```json
{
  "task_id": 9001,
  "status": "queued",
  "format": "pdf",
  "engine": "mineru",
  "poll": "/api/v1/tasks/9001",
  "message": "PDF 解析为异步任务，请轮询任务结果"
}
```

- 轮询 `GET /api/v1/tasks/9001`，返回的 `result` 字段就是 Markdown
- 使用现有任务队列、并发控制和 WebSocket 进度推送

```bash
curl -X POST http://192.168.0.8:5553/api/v1/convert/markdown \
  -H "X-API-Key: ak_xxx" \
  -F "file=@招标文件.pdf" \
  -F "engine=mineru"
```

### POST /api/v1/convert/docx

| 表单字段 | 必填 | 说明 |
|---|---|---|
| `file` | 是 | `.doc` / `.docx` / `.odt` / `.rtf` |

- `.docx`：直接返回原文件
- `.doc` / `.odt` / `.rtf`：LibreOffice 转 DOCX
- 响应为 DOCX 二进制，`Content-Disposition: attachment`

```bash
curl -X POST http://192.168.0.8:5553/api/v1/convert/docx \
  -H "X-API-Key: ak_xxx" \
  -F "file=@旧文档.doc" \
  -o 旧文档.docx
```

## 6. 结果目录

每个任务结果位于 `data/results/<task_id>/`：

| 文件 | 说明 |
|---|---|
| `result.docx` | Word 结果（勾选 docx 时生成；非图片型 PDF 为 exactdoc 直转） |
| `result.md` | Markdown 结果（OCR/引擎产物，用于预览） |
| `result.txt` | 纯文本（勾选 txt 时生成） |
| `result.json` | JSON 结果（勾选 json 时生成） |
| `result.raw.json` | 引擎原始响应（如有） |
| `source_<原文件名>` | 源文件副本 |
| `images/` | OCR 提取的图片 |
| `ppocrv6_data.json` | PP-OCRv6 坐标数据（仅 ppocrv6） |
| `*_dxf.md` | DXF 文字提取结果（仅 CAD） |

---

## 7. 配置项

以下配置可写入 `.env`；其中精修轮数、最大页数、转换超时三项已加入管理面板「系统设置」在线修改：

| 配置 | 默认值 | 说明 |
|---|---|---|
| `PDF_DOCX_DIRECT_ENABLED` | `true` | 是否启用非图片型 PDF 直转 DOCX |
| `PDF_DOCX_REFINE_ROUNDS` | `3` | exactdoc 精修轮数；`0` 最快，但页数偏差较大 |
| `PDF_DOCX_MAX_PAGES` | `500` | 超过页数回退 OCR→MD→DOCX；`0` 表示不限制 |
| `PDF_DOCX_TIMEOUT` | `1800` | 单次 exactdoc 转换超时（秒） |
| `OFFICE_MARKDOWN_TIMEOUT` | `300` | DOCX→Markdown 的 Pandoc 超时（秒） |

`PDF_DOCX_DIRECT_ENABLED` 为布尔开关，需写入 `.env`；其余三项可在管理面板在线修改。

---

## 8. 已知限制

- exactdoc 是**版面重建**，不保证页级完全一致；测试中 195 页表格型招标文件在 `refine 3` 下为 201 页（+3.1%）
- 复杂设计稿、年报、多栏画册、密集公式的还原度有限
- 默认最多 500 页，超过会回退 OCR 链路
- 图片型 PDF 不走 exactdoc，仍是 OCR 文字重建
- `docx-only` 快速路径下 `result.md` 是 DOCX 提取文本，仅用于预览
- 下载接口优先返回已保存的 `result.docx`；未勾选 `docx` 时才会从 `result.md` 现场生成
- DOCX→Markdown 的图片内联为 data URI，图片多时 Markdown 体积会明显增大
- DOC→DOCX / DOC→Markdown 依赖 LibreOffice；无 LibreOffice 时回退原 OCR 流程
- PDF→Markdown 是异步任务；DOCX/DOC→Markdown 是同步接口
- 同步转换接口最多 2 并发；Pandoc 超时默认 300s
- DOCX→Markdown 图片内联限制单张 20MB、总量 50MB；DOCX 解压后超过 500MB 会被拒绝

---

## 9. 许可证说明

- exactdoc：Apache-2.0
- 默认依赖：pypdfium2、python-docx、numpy、pillow、lxml（均为宽松许可）
- 本项目不引入 PyMuPDF，避免 AGPL 网络条款

---

## 10. 版本

当前版本见根目录 `CHANGELOG.md`，也可通过以下接口获取：

```http
GET /api/version
```

```json
{
  "ui_version": "1.3.0",
  "engine_version": "PaddleOCR-VL-1.6-0.9B"
}
```
