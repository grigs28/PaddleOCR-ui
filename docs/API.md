# PaddleOCR-UI API 调用文档

> Base URL: `http://192.168.0.19:5553`
>
> 所有接口（除登录/回调外）均需认证，支持两种方式：
> - **Cookie**: 浏览器登录后自动携带 `paddleocr_session`
> - **API Key**: 请求头 `X-API-Key: ak_xxxxx`

---

## 1. 认证

### 1.1 获取 API Key（需浏览器登录）

```
POST /auth/api-keys?name=我的Key
Cookie: paddleocr_session=xxx
```

**响应：**
```json
{
  "api_key": "ak_12faee9159de3d5ed6b006b37bb0def51b1c7971cadb687b981a6b9daba4f1",
  "message": "请妥善保存，此 Key 仅显示一次"
}
```

### 1.2 查看 API Key 列表

```
GET /auth/api-keys
Cookie: paddleocr_session=xxx
```

### 1.3 吊销 API Key

```
DELETE /auth/api-keys/{key_id}
Cookie: paddleocr_session=xxx
```

### 1.4 查看当前用户信息

```
GET /auth/me
```

**响应：**
```json
{
  "user_id": 2,
  "username": "grigs",
  "display_name": "屈秦晖",
  "is_admin": 1
}
```

---

## 2. OCR 任务

### 2.1 提交 OCR 任务

```
POST /api/v1/tasks
Content-Type: multipart/form-data
X-API-Key: ak_xxxxx
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `file` | File | 是 | 待识别文件 |
| `task_type` | string | 否 | 任务类型，固定 `ocr` |
| `output_formats` | string | 否 | JSON 数组，输出格式。默认 `["markdown"]` |

**支持的文件类型：** pdf, jpg, jpeg, png, bmp, tiff, tif, webp, docx, xlsx

**支持的输出格式：** markdown, json, txt, docx

**文件大小限制：** 1GB

**请求示例：**

```bash
curl -X POST \
  -H "X-API-Key: ak_xxxxx" \
  -F "file=@/path/to/document.pdf" \
  -F 'output_formats=["markdown","json"]' \
  http://192.168.0.19:5553/api/v1/tasks
```

**Python 示例：**

```python
import requests

url = "http://192.168.0.19:5553/api/v1/tasks"
headers = {"X-API-Key": "ak_xxxxx"}

with open("document.pdf", "rb") as f:
    resp = requests.post(url, headers=headers, files={
        "file": f,
    }, data={
        "task_type": "ocr",
        "output_formats": '["markdown", "json"]',
    })
    print(resp.json())
```

**响应：**
```json
{
  "task_id": 27,
  "message": "任务已提交"
}
```

### 2.2 查询任务列表

```
GET /api/v1/tasks?page=1&size=20
X-API-Key: ak_xxxxx
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `size` | int | 20 | 每页条数 |

**响应：**
```json
{
  "tasks": [
    {
      "id": 27,
      "status": "completed",
      "task_type": "ocr",
      "input_filename": "document.pdf",
      "input_file_size": 6520129,
      "progress": 100,
      "page_current": 83,
      "page_total": 83,
      "created_at": "2026-04-19T13:20:15.305499",
      "completed_at": "2026-04-19T21:20:44.615606",
      "output_formats": "[\"markdown\", \"json\"]",
      "processing_time": 25
    }
  ]
}
```

**status 取值：**

| 值 | 说明 |
|----|------|
| `pending` | 等待中 |
| `queued` | 已入队 |
| `processing` | 处理中 |
| `completed` | 已完成 |
| `failed` | 失败 |
| `cancelled` | 已取消 |

### 2.3 查询任务详情（含识别结果）

```
GET /api/v1/tasks/{task_id}
X-API-Key: ak_xxxxx
```

**响应：**
```json
{
  "task": {
    "id": 27,
    "status": "completed",
    "task_type": "ocr",
    "input_filename": "document.pdf",
    "input_file_size": 6520129,
    "output_formats": "[\"markdown\", \"json\"]",
    "progress": 100,
    "page_current": 83,
    "page_total": 83,
    "error_message": null,
    "created_at": "2026-04-19T13:20:15.305499",
    "started_at": "2026-04-19T21:20:19.305499",
    "completed_at": "2026-04-19T21:20:44.615606",
    "processing_time": 25
  },
  "result": "# 文档标题\n\n识别出的 Markdown 内容..."
}
```

### 2.4 取消任务

```
DELETE /api/v1/tasks/{task_id}
X-API-Key: ak_xxxxx
```

只能取消 `pending` 或 `queued` 状态的任务。

**响应：**
```json
{ "message": "任务已取消" }
```

---

## 3. 文件管理

### 3.1 文件列表

```
GET /api/v1/files?page=1&size=20&search=&status=
X-API-Key: ak_xxxxx
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `page` | int | 1 | 页码 |
| `size` | int | 20 | 每页条数（最大100） |
| `search` | string | - | 按文件名模糊搜索 |
| `status` | string | - | 按状态筛选：`completed` / `failed` |

**响应：**
```json
{
  "files": [
    {
      "id": 27,
      "filename": "document.pdf",
      "file_size": 6520129,
      "file_type": "pdf",
      "status": "completed",
      "progress": 100,
      "output_formats": "[\"markdown\", \"json\"]",
      "processing_time": 25,
      "deleted": 0,
      "created_at": "2026-04-19T13:20:15.305499",
      "completed_at": "2026-04-19T21:20:44.615606"
    }
  ],
  "total": 5,
  "page": 1,
  "size": 20
}
```

管理员额外返回 `user_id` 和 `username` 字段。

### 3.2 下载结果文件

```
GET /api/v1/files/{file_id}/download?format=md
X-API-Key: ak_xxxxx
```

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| `format` | string | `md` | 下载格式：`md` / `txt` / `docx` |

**请求示例：**

```bash
# 下载 Markdown
curl -O -H "X-API-Key: ak_xxxxx" \
  "http://192.168.0.19:5553/api/v1/files/27/download?format=md"

# 下载纯文本
curl -O -H "X-API-Key: ak_xxxxx" \
  "http://192.168.0.19:5553/api/v1/files/27/download?format=txt"

# 下载 DOCX
curl -O -H "X-API-Key: ak_xxxxx" \
  "http://192.168.0.19:5553/api/v1/files/27/download?format=docx"
```

### 3.3 批量下载

```
POST /api/v1/files/batch-download
Content-Type: application/json
X-API-Key: ak_xxxxx
```

**请求体：**
```json
{
  "file_ids": [20, 21, 22],
  "format": "md"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `file_ids` | int[] | 文件 ID 列表 |
| `format` | string | `md` / `txt` / `docx`，默认 `md` |

**响应：** ZIP 压缩包 (`application/zip`)

```bash
curl -o results.zip -H "X-API-Key: ak_xxxxx" \
  -H "Content-Type: application/json" \
  -d '{"file_ids":[20,21,22],"format":"md"}' \
  http://192.168.0.19:5553/api/v1/files/batch-download
```

### 3.4 预览原文件

```
GET /api/v1/files/{file_id}/preview
X-API-Key: ak_xxxxx
```

返回原始文件（图片返回对应 MIME 类型，PDF 返回 `application/pdf`）。

### 3.5 删除文件

```
DELETE /api/v1/files/{file_id}
X-API-Key: ak_xxxxx
```

- **普通用户**：软删除（标记删除，不删文件）
- **管理员**：硬删除（删除文件 + 数据库标记）

**响应：**
```json
{ "message": "已删除", "hard_delete": false }
```

---

## 4. 完整调用流程

### Python 完整示例

```python
import requests
import time

BASE = "http://192.168.0.19:5553"
HEADERS = {"X-API-Key": "ak_xxxxx"}


def ocr_file(file_path, formats=None):
    """提交 OCR 任务并等待结果"""

    # 1. 提交任务
    with open(file_path, "rb") as f:
        resp = requests.post(f"{BASE}/api/v1/tasks", headers=HEADERS, files={
            "file": f,
        }, data={
            "output_formats": str(formats or ["markdown"]),
        })
    data = resp.json()
    task_id = data["task_id"]
    print(f"任务已提交, task_id={task_id}")

    # 2. 轮询等待完成
    while True:
        time.sleep(3)
        resp = requests.get(f"{BASE}/api/v1/tasks/{task_id}", headers=HEADERS)
        task = resp.json()["task"]
        status = task["status"]
        progress = task["progress"]
        print(f"状态: {status}, 进度: {progress}%")

        if status == "completed":
            break
        elif status == "failed":
            raise Exception(f"任务失败: {task.get('error_message')}")

    # 3. 获取识别结果
    resp = requests.get(f"{BASE}/api/v1/tasks/{task_id}", headers=HEADERS)
    result = resp.json()["result"]
    print(f"识别完成, 结果长度: {len(result)} 字符")

    # 4. 下载指定格式
    for fmt in (formats or ["markdown"]):
        ext = {"markdown": "md", "json": "json", "txt": "txt", "docx": "docx"}[fmt]
        resp = requests.get(
            f"{BASE}/api/v1/files/{task_id}/download",
            headers=HEADERS,
            params={"format": ext},
        )
        with open(f"result_{task_id}.{ext}", "wb") as f:
            f.write(resp.content)
        print(f"已下载: result_{task_id}.{ext} ({len(resp.content)} bytes)")

    return result


if __name__ == "__main__":
    text = ocr_file("test.pdf", formats=["markdown", "json"])
    print(text[:500])
```

### curl 完整流程

```bash
API="http://192.168.0.19:5553"
KEY="X-API-Key: ak_xxxxx"

# 1. 提交
TASK=$(curl -s -H "$KEY" -F "file=@test.pdf" -F 'output_formats=["markdown","json"]' $API/api/v1/tasks)
echo $TASK
# {"task_id":27,"message":"任务已提交"}

# 2. 查状态
curl -s -H "$KEY" $API/api/v1/tasks/27 | python3 -m json.tool

# 3. 获取结果
curl -s -H "$KEY" $API/api/v1/tasks/27 | python3 -c "import json,sys; print(json.load(sys.stdin)['result'][:200])"

# 4. 下载
curl -O -H "$KEY" "$API/api/v1/files/27/download?format=md"
curl -O -H "$KEY" "$API/api/v1/files/27/download?format=json"
curl -O -H "$KEY" "$API/api/v1/files/27/download?format=docx"
```

---

## 5. 错误码

| HTTP 状态码 | 说明 |
|-------------|------|
| 200 | 成功 |
| 400 | 请求参数错误（文件类型不支持、文件过大等） |
| 401 | 未登录或 API Key 无效 |
| 403 | 权限不足（如非管理员访问管理接口） |
| 404 | 资源不存在 |
| 422 | 请求格式错误 |

**错误响应格式：**
```json
{ "detail": "错误描述" }
```

---

## 6. WebSocket 实时进度（可选）

```
ws://192.168.0.19:5553/ws/progress?session_id=xxx
```

连接后，当任务状态变化时服务端推送：

```json
{
  "task_id": 27,
  "status": "processing",
  "progress": 43
}
```

> 建议同时使用 HTTP 轮询作为兜底（每 5 秒 `GET /api/v1/tasks`）。
