# ACADxPDF 集成设计：DWG↔PDF 双向转换 + DXF 文字提取

## 目标

集成新版 ACADxPDF API（192.168.0.5:5557），实现 DWG→PDF+DXF 文字提取和 PDF→DWG 双向转换，通过输出格式勾选自动判断转换方向。

## API 能力

| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/convert` | POST | DWG→PDF+DXF（异步，返回 task_id） |
| `/tasks` | GET | 列出 DWG 任务 |
| `/download/{task_id}` | GET | 下载 DWG 任务结果 ZIP |
| `/convert-pdf` | POST | PDF→DWG（异步，返回 task_id） |
| `/pdf-tasks` | GET | 列出 PDF 任务 |
| `/pdf-task/{task_id}` | GET | 查询 PDF 任务状态 |
| `/download-pdf-zip/{task_id}` | GET | 下载 PDF 任务结果 ZIP |
| `/convert-pdf/add/{task_id}` | POST | 追加文件到运行中任务 |

认证：`x-api-key` header。所有任务均为异步模式，需轮询状态。

## 文件处理路由

| 上传文件 | output_formats 含 dwg | 走哪条路 | 输出 |
|---------|----------------------|---------|------|
| DWG/DXF | 忽略此标志 | DXF 文字提取 | Markdown/JSON/TXT/DOCX |
| PDF | 是 | PDF→DWG 转换 | 仅 DWG |
| PDF | 否 | OCR（现有逻辑） | Markdown/JSON/TXT/DOCX |
| 图片/Office | 忽略此标志 | OCR（现有逻辑） | 全选 |

## 前端改动

### UploadArea.vue + stores/upload.js

1. **输出格式新增 DWG 选项**：`availableFormats` 添加 `{ value: 'dwg', label: 'DWG' }`
2. **条件显示**：DWG 输出选项仅在上传文件包含 PDF 时可见；DWG/DXF/图片/Office 上传时隐藏
3. **混合校验**：同一次上传不允许 DWG 和 PDF 混合（前端拦截提示）

### 文件校验逻辑

```
pendingFiles 中有 DWG 且有 PDF → 提示"不能同时上传 DWG 和 PDF 文件" → 阻止上传
```

## 后端改动

### config.py

- `acad_service_url` 更新默认值为 `http://192.168.0.5:5557`
- `acad_service_apikey` 已有，填入 `axp-8fc2a57f4fccf5a561acab20588ae533`

### doc_converter.py — ACAD 客户端改造

替换现有 `_convert_dwg_via_acad` 为异步轮询模式：

1. **DWG→PDF+DXF**：`POST /convert` → 轮询 `GET /tasks`（间隔 5 秒，超时 config.libreoffice_timeout）→ `GET /download/{task_id}` 下载 ZIP → 解压获取 PDF 和 DXF
2. **新增 PDF→DWG**：`POST /convert-pdf` → 轮询 `GET /pdf-task/{id}` → `GET /download-pdf-zip/{id}` 下载 ZIP → 解压获取 DWG。函数签名：`async def convert_pdf_to_dwg(input_path: str, output_dir: str) -> str | None`，返回 DWG 文件路径。

所有请求带 `x-api-key` header。

### task_engine.py — 新增 PDF→DWG 分支

在 `is_pdf_file` 分支内增加判断：

```python
if is_pdf_file(filename):
    output_formats = json.loads(task.output_formats or '["markdown"]')
    if 'dwg' in output_formats:
        # PDF→DWG 转换
        dwg_path = await convert_pdf_to_dwg(file_path, output_dir)
        # 保存 DWG 到结果目录，不走 OCR
        ...
    else:
        # 现有 OCR 逻辑
        ocr_result = await ocr_client.recognize_pdf(file_path)
```

### DXF 控制字符清理

`extract_dxf_text()` 和 `md_to_docx()` 中过滤 `\x00-\x1f` 控制字符（保留 `\n\r\t`），避免 DOCX 生成时 XML 报错。

## 验证标准

1. 上传 DWG → 生成 Markdown/JSON/TXT/DOCX（含 DXF 文字提取）
2. 上传 PDF 勾选 DWG → 生成 DWG 文件
3. 上传 PDF 不勾 DWG → 走 OCR 生成 Markdown 等
4. DWG 和 PDF 混合上传 → 前端拦截提示
5. DXF 文字提取的 DOCX 无 XML 报错
