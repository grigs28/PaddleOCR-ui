# PaddleOCR UI 重构实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将简单任务列表重构为专业级文档 OCR 工作台，左右分栏对比、文件管理、后台管理。

**Architecture:** Vue 3 + Element Plus + Pinia 细粒度 Store + WebSocket 实时进度。后端 FastAPI 新增文件管理/管理员 API。前端 Tab 单页切换，上传逻辑放 store 中不受 Tab 切换影响。

**Tech Stack:** FastAPI, SQLAlchemy async, Vue 3, Element Plus, Pinia, markdown-it, pdfjs-dist, @vueuse/core, python-docx, zipfile

---

## 文件变更清单

### 后端新建
- `backend/api/file_router.py` — 文件管理 API（列表/下载/批量下载/删除）
- `backend/api/admin_router.py` — 管理员 API（用户列表/修改角色）
- `backend/services/export_service.py` — 输出格式转换（MD→TXT, MD→DOCX, ZIP 打包）

### 后端修改
- `backend/config.py` — max_file_size_mb 默认改为 1024 (1GB)
- `backend/main.py` — 注册 file_router, admin_router
- `backend/api/ocr_router.py` — list_tasks 管理员看全部、返回原始文件路径
- `backend/services/task_engine.py` — 接入 progress_manager 推送 WebSocket 进度

### 前端新建
- `frontend/src/stores/user.js` — 用户信息 store（登录态、is_admin）
- `frontend/src/stores/upload.js` — 上传队列 store（文件列表、上传进度、Tab切换不阻断）
- `frontend/src/stores/task.js` — 任务队列 store（活跃任务、WebSocket进度、完成归档）
- `frontend/src/stores/file.js` — 文件管理 store（已归档文件列表、分页、筛选）
- `frontend/src/composables/useWebSocket.js` — WebSocket 连接管理（自动重连）
- `frontend/src/composables/useUpload.js` — 上传逻辑 composable
- `frontend/src/utils/format.js` — 格式化工具（文件大小、状态文本、时间）
- `frontend/src/components/UploadArea.vue` — 拖拽上传区域
- `frontend/src/components/FilePreview.vue` — PDF/图片原文件预览
- `frontend/src/components/TaskQueue.vue` — 转换队列（虚拟滚动）
- `frontend/src/components/MarkdownPreview.vue` — Markdown 结果预览
- `frontend/src/components/FileTable.vue` — 文件管理表格
- `frontend/src/components/AdminUserTable.vue` — 用户管理表格
- `frontend/src/views/MainView.vue` — 主布局（Tab 容器 + 顶栏）
- `frontend/src/views/TaskWorkspace.vue` — Tab1 上传任务左右分栏
- `frontend/src/views/FileManagement.vue` — Tab2 文件管理
- `frontend/src/views/AdminPanel.vue` — Tab3 管理后台

### 前端修改
- `frontend/src/router/index.js` — 简化为单路由，MainView 内部 Tab 切换
- `frontend/src/main.js` — 无变更
- `frontend/src/App.vue` — 无变更
- `frontend/package.json` — 新增 markdown-it, pdfjs-dist

### 删除（旧视图，功能已被新组件替代）
- `frontend/src/views/DashboardView.vue`
- `frontend/src/views/TaskDetailView.vue`
- `frontend/src/views/AdminView.vue`
- `frontend/src/views/ApiDocsView.vue`
- `frontend/src/layouts/MainLayout.vue`

---

## Pinia Store 接口定义（前后端并行开发契约）

### user.js
```js
// State
{ info: { user_id, username, display_name, is_admin } | null, loaded: false }
// Actions
fetchUser()          // GET /auth/me
isAdmin()            // getter: info?.is_admin === 1
```

### upload.js
```js
// State
{ files: [], uploading: false }
// 每个 file: { id, raw: File, name, size, status: 'pending'|'uploading'|'done'|'error', taskId, progress }
// Actions
addFiles(fileList)          // 添加文件到队列，检查 1GB 限制
startUpload()               // 逐个 POST /api/v1/tasks
removeFile(index)           // 移除文件
clearCompleted()            // 清除已完成
// 重点：upload 逻辑在 store 中，不依赖组件生命周期，Tab 切换不阻断
```

### task.js
```js
// State
{ activeTasks: [], selectedTaskId: null, resultText: '' }
// activeTasks: 从 GET /api/v1/tasks 恢复 status != completed 的任务
// Actions
fetchActive()                         // GET /api/v1/tasks，只保留非 completed
selectTask(taskId)                    // 设置选中任务，获取详情和结果
updateTaskProgress(taskId, data)      // WebSocket 推送更新
archiveCompleted(taskId)              // 完成后从 activeTasks 移除，触发 fileStore.fetchFiles()
restoreFromApi()                      // 页面加载时从 API 恢复进行中的任务
```

### file.js
```js
// State
{ files: [], total: 0, page: 1, pageSize: 20, search: '', statusFilter: '' }
// Actions
fetchFiles()                           // GET /api/v1/files
downloadFile(fileId, format)           // GET /api/v1/files/{id}/download?format=
batchDownload(fileIds)                 // POST /api/v1/files/batch-download
deleteFile(fileId)                     // DELETE /api/v1/files/{id}
```

---

## Task 1: 后端 — 文件管理 API + 管理员 API + 导出服务

**Files:**
- Create: `backend/api/file_router.py`
- Create: `backend/api/admin_router.py`
- Create: `backend/services/export_service.py`
- Modify: `backend/config.py:37` — max_file_size_mb 改 1024
- Modify: `backend/main.py` — 注册新 router
- Modify: `backend/api/ocr_router.py:91-120` — 管理员看全部、返回 input_file_path
- Modify: `backend/services/task_engine.py` — 接入 progress_manager

### file_router.py

```python
import os
import zipfile
import io
import tempfile
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select, desc, func, or_

from backend.api.ocr_router import _get_user_id
from backend.auth.session import SessionManager
from backend.config import get_settings
from backend.database import async_session
from backend.models.task import Task
from backend.services.export_service import ExportService

router = APIRouter(prefix="/api/v1/files", tags=["文件管理"])


async def _get_user_id_and_role(request: Request) -> tuple[int, bool]:
    """返回 (user_id, is_admin)"""
    settings = get_settings()
    session_mgr = SessionManager()

    session_id = request.cookies.get(settings.session_cookie_name)
    if session_id:
        user = session_mgr.get_session(session_id)
        if user:
            return user["user_id"], bool(user.get("is_admin"))

    from backend.auth.api_key import ApiKeyManager
    api_key = request.headers.get("X-API-Key")
    if api_key:
        result = await ApiKeyManager.verify_key(api_key)
        if result:
            async with async_session() as s:
                from backend.models.user import User
                r = await s.execute(select(User).where(User.id == result["user_id"]))
                u = r.scalar_one_or_none()
                if u:
                    return u.id, bool(u.is_admin)

    raise HTTPException(status_code=401, detail="未登录")


@router.get("")
async def list_files(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    search: str = Query(""),
    status: str = Query(""),
):
    user_id, is_admin = await _get_user_id_and_role(request)

    async with async_session() as session:
        query = select(Task)
        count_query = select(func.count(Task.id))

        if not is_admin:
            query = query.where(Task.user_id == user_id)
            count_query = count_query.where(Task.user_id == user_id)

        if search:
            query = query.where(Task.input_filename.ilike(f"%{search}%"))
            count_query = count_query.where(Task.input_filename.ilike(f"%{search}%"))
        if status:
            query = query.where(Task.status == status)
            count_query = count_query.where(Task.status == status)

        total_res = await session.execute(count_query)
        total = total_res.scalar()

        query = query.order_by(desc(Task.created_at)).offset((page - 1) * size).limit(size)
        result = await session.execute(query)
        tasks = result.scalars().all()

        items = []
        for t in tasks:
            item = {
                "id": t.id,
                "filename": t.input_filename,
                "file_size": t.input_file_size,
                "file_type": os.path.splitext(t.input_filename or "")[1].lstrip("."),
                "status": t.status,
                "progress": t.progress,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            }
            if is_admin:
                item["user_id"] = t.user_id
            items.append(item)

        return {"files": items, "total": total, "page": page, "size": size}


@router.get("/{file_id}/download")
async def download_file(file_id: int, request: Request, format: str = Query("md")):
    user_id, is_admin = await _get_user_id_and_role(request)

    async with async_session() as session:
        query = select(Task).where(Task.id == file_id)
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="文件不存在")
        if task.status != "completed":
            raise HTTPException(status_code=400, detail="任务未完成")

        md_path = os.path.join(task.result_path, "result.md") if task.result_path else None
        if not md_path or not os.path.exists(md_path):
            raise HTTPException(status_code=404, detail="结果文件不存在")

        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()

        base_name = os.path.splitext(task.input_filename or "result")[0]

        if format == "txt":
            content = ExportService.md_to_txt(md_text)
            return StreamingResponse(
                io.BytesIO(content.encode("utf-8")),
                media_type="text/plain",
                headers={"Content-Disposition": f"attachment; filename={base_name}.txt"},
            )
        elif format == "docx":
            docx_bytes = ExportService.md_to_docx(md_text)
            return StreamingResponse(
                io.BytesIO(docx_bytes),
                media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                headers={"Content-Disposition": f"attachment; filename={base_name}.docx"},
            )
        else:
            return FileResponse(
                md_path,
                media_type="text/markdown",
                filename=f"{base_name}.md",
            )


@router.post("/batch-download")
async def batch_download(request: Request):
    body = await request.json()
    file_ids = body.get("file_ids", [])
    if not file_ids:
        raise HTTPException(status_code=400, detail="请选择文件")

    user_id, is_admin = await _get_user_id_and_role(request)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        async with async_session() as session:
            query = select(Task).where(Task.id.in_(file_ids))
            if not is_admin:
                query = query.where(Task.user_id == user_id)
            result = await session.execute(query)
            tasks = result.scalars().all()

            for task in tasks:
                if task.status != "completed" or not task.result_path:
                    continue
                md_path = os.path.join(task.result_path, "result.md")
                if os.path.exists(md_path):
                    base_name = os.path.splitext(task.input_filename or "result")[0]
                    with open(md_path, "r", encoding="utf-8") as f:
                        zf.writestr(f"{base_name}.md", f.read())

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=ocr_results.zip"},
    )


@router.delete("/{file_id}")
async def delete_file(file_id: int, request: Request):
    user_id, is_admin = await _get_user_id_and_role(request)

    async with async_session() as session:
        query = select(Task).where(Task.id == file_id)
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="文件不存在")

        # 删除文件
        if task.input_file_path and os.path.exists(task.input_file_path):
            import shutil
            parent = os.path.dirname(task.input_file_path)
            if os.path.isdir(parent):
                shutil.rmtree(parent, ignore_errors=True)
        if task.result_path and os.path.exists(task.result_path):
            import shutil
            shutil.rmtree(task.result_path, ignore_errors=True)

        await session.delete(task)
        await session.commit()
        return {"message": "已删除"}
```

### admin_router.py

```python
from fastapi import APIRouter, Request, HTTPException
from sqlalchemy import select

from backend.api.ocr_router import _get_user_id
from backend.database import async_session
from backend.models.user import User

router = APIRouter(prefix="/api/v1/admin", tags=["管理后台"])


async def _require_admin(request: Request) -> int:
    user_id = await _get_user_id(request)
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user or not user.is_admin:
            raise HTTPException(status_code=403, detail="需要管理员权限")
        return user_id


@router.get("/users")
async def list_users(request: Request):
    await _require_admin(request)
    async with async_session() as session:
        result = await session.execute(select(User).order_by(User.id))
        users = result.scalars().all()
        return {
            "users": [
                {
                    "id": u.id,
                    "username": u.username,
                    "display_name": u.display_name,
                    "is_admin": u.is_admin,
                    "created_at": u.created_at.isoformat() if u.created_at else None,
                }
                for u in users
            ]
        }


@router.put("/users/{user_id}")
async def update_user(user_id: int, request: Request):
    await _require_admin(request)
    body = await request.json()
    async with async_session() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        if "is_admin" in body:
            user.is_admin = int(body["is_admin"])
        if "display_name" in body:
            user.display_name = body["display_name"]
        await session.commit()
        return {"message": "已更新"}
```

### export_service.py

```python
import re
from docx import Document
from docx.shared import Pt


class ExportService:
    @staticmethod
    def md_to_txt(md_text: str) -> str:
        """Markdown 转纯文本：去除 #、**、[]() 等标记"""
        text = md_text
        text = re.sub(r'!\[.*?\]\(.*?\)', '', text)  # 去图片
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # 链接保留文字
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)  # 去标题标记
        text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)  # 去粗体斜体
        text = re.sub(r'`([^`]+)`', r'\1', text)  # 去行内代码
        return text.strip()

    @staticmethod
    def md_to_docx(md_text: str) -> bytes:
        """Markdown 转 DOCX"""
        import io
        doc = Document()
        for line in md_text.split('\n'):
            if line.startswith('# '):
                doc.add_heading(line[2:], level=1)
            elif line.startswith('## '):
                doc.add_heading(line[3:], level=2)
            elif line.startswith('### '):
                doc.add_heading(line[4:], level=3)
            elif line.strip():
                doc.add_paragraph(line)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()
```

### config.py 修改
`max_file_size_mb: int = 1024`

### main.py 注册路由
```python
from backend.api.file_router import router as file_router
from backend.api.admin_router import router as admin_router
# 在已有 include_router 之后添加:
app.include_router(file_router)
app.include_router(admin_router)
```

### ocr_router.py 修改 list_tasks
管理员看全部任务，返回 input_file_path 用于预览：
```python
@router.get("/tasks")
async def list_tasks(request: Request, page: int = 1, size: int = 20):
    user_id = await _get_user_id(request)
    is_admin = False
    async with async_session() as s:
        from backend.models.user import User
        r = await s.execute(select(User).where(User.id == user_id))
        u = r.scalar_one_or_none()
        if u:
            is_admin = bool(u.is_admin)

    async with async_session() as session:
        query = select(Task).order_by(desc(Task.created_at))
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        query = query.offset((page - 1) * size).limit(size)
        result = await session.execute(query)
        tasks = result.scalars().all()
        return {
            "tasks": [
                {
                    "id": t.id,
                    "status": t.status,
                    "task_type": t.task_type,
                    "input_filename": t.input_filename,
                    "input_file_size": t.input_file_size,
                    "progress": t.progress,
                    "page_current": t.page_current,
                    "page_total": t.page_total,
                    "created_at": t.created_at.isoformat() if t.created_at else None,
                    "completed_at": t.completed_at.isoformat() if t.completed_at else None,
                }
                for t in tasks
            ]
        }
```

### task_engine.py 接入 WebSocket 进度推送
在 `_update_status` 和 `_process_task` 中添加 progress_manager.send_progress 调用：
```python
# 在 _update_status 末尾添加:
from backend.ws.progress import progress_manager
async with async_session() as s:
    r = await s.execute(select(Task).where(Task.id == task_id))
    t = r.scalar_one_or_none()
    if t:
        await progress_manager.send_progress(t.user_id, task_id, {
            "status": status,
            "progress": t.progress if t else 0,
            "error": error,
        })
```

---

## Task 2: 前端 — Stores + Router + Composables

**Files:**
- Create: `frontend/src/stores/user.js`
- Create: `frontend/src/stores/upload.js`
- Create: `frontend/src/stores/task.js`
- Create: `frontend/src/stores/file.js`
- Create: `frontend/src/composables/useWebSocket.js`
- Create: `frontend/src/composables/useUpload.js`
- Create: `frontend/src/utils/format.js`
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/package.json` — 添加 markdown-it

### stores/user.js
```js
import { defineStore } from 'pinia'
import axios from 'axios'

export const useUserStore = defineStore('user', {
  state: () => ({ info: null, loaded: false }),
  getters: {
    isAdmin: (state) => state.info?.is_admin === 1,
    displayName: (state) => state.info?.display_name || '用户',
  },
  actions: {
    async fetchUser() {
      try {
        const { data } = await axios.get('/auth/me')
        this.info = data
      } catch {
        this.info = null
      }
      this.loaded = true
    },
  },
})
```

### stores/upload.js
```js
import { defineStore } from 'pinia'
import axios from 'axios'

const MAX_FILE_SIZE = 1024 * 1024 * 1024 // 1GB

export const useUploadStore = defineStore('upload', {
  state: () => ({
    files: [],       // { id, raw, name, size, status, taskId, errorMsg }
    uploading: false,
  }),
  getters: {
    pendingFiles: (state) => state.files.filter(f => f.status === 'pending'),
    hasFiles: (state) => state.files.length > 0,
  },
  actions: {
    addFiles(fileList) {
      for (const file of fileList) {
        if (file.size > MAX_FILE_SIZE) {
          file._error = `文件 ${file.name} 超过 1GB 限制`
          continue
        }
        this.files.push({
          id: Date.now() + Math.random(),
          raw: file,
          name: file.name,
          size: file.size,
          status: 'pending',
          taskId: null,
          errorMsg: null,
        })
      }
    },
    removeFile(id) {
      const idx = this.files.findIndex(f => f.id === id)
      if (idx !== -1) this.files.splice(idx, 1)
    },
    async startUpload() {
      this.uploading = true
      const { useTaskStore } = await import('./task')
      const taskStore = useTaskStore()

      for (const file of this.files.filter(f => f.status === 'pending')) {
        file.status = 'uploading'
        try {
          const formData = new FormData()
          formData.append('file', file.raw)
          formData.append('task_type', 'ocr')
          formData.append('output_formats', JSON.stringify(['markdown']))
          const { data } = await axios.post('/api/v1/tasks', formData)
          file.taskId = data.task_id
          file.status = 'done'
          // 加入活跃任务队列
          taskStore.addActiveTask({ id: data.task_id, input_filename: file.name, input_file_size: file.size, status: 'queued', progress: 0 })
        } catch (e) {
          file.status = 'error'
          file.errorMsg = e.response?.data?.detail || '上传失败'
        }
      }
      this.uploading = false
      // 清除已完成的上传项
      this.files = this.files.filter(f => f.status === 'pending' || f.status === 'error')
    },
    clearCompleted() {
      this.files = this.files.filter(f => f.status !== 'done')
    },
  },
})
```

### stores/task.js
```js
import { defineStore } from 'pinia'
import axios from 'axios'

export const useTaskStore = defineStore('task', {
  state: () => ({
    activeTasks: [],     // 进行中的任务
    selectedTaskId: null,
    selectedResult: '',
    selectedPreview: null,  // { url, type: 'pdf'|'image' }
  }),
  actions: {
    async fetchActive() {
      const { data } = await axios.get('/api/v1/tasks')
      // 只保留非完成状态的任务到 activeTasks
      this.activeTasks = (data.tasks || []).filter(t => t.status !== 'completed')
      // 完成的归档到 fileStore
      const completed = (data.tasks || []).filter(t => t.status === 'completed')
      if (completed.length > 0) {
        const { useFileStore } = await import('./file')
        // fileStore 会自己 fetchFiles，这里只需触发
      }
    },
    addActiveTask(task) {
      this.activeTasks.unshift(task)
    },
    async selectTask(taskId) {
      this.selectedTaskId = taskId
      if (!taskId) {
        this.selectedResult = ''
        this.selectedPreview = null
        return
      }
      try {
        const { data } = await axios.get(`/api/v1/tasks/${taskId}`)
        this.selectedResult = data.result || ''
        // 构建原文件预览 URL
        const task = data.task
        if (task.input_filename) {
          const ext = task.input_filename.split('.').pop().toLowerCase()
          if (['pdf'].includes(ext)) {
            this.selectedPreview = { url: `/api/v1/files/${taskId}/preview`, type: 'pdf' }
          } else if (['jpg','jpeg','png','bmp','tiff','tif','webp'].includes(ext)) {
            this.selectedPreview = { url: `/api/v1/files/${taskId}/preview`, type: 'image' }
          }
        }
      } catch {
        this.selectedResult = ''
        this.selectedPreview = null
      }
    },
    updateTaskProgress(taskId, data) {
      const task = this.activeTasks.find(t => t.id === taskId)
      if (task) {
        if (data.status) task.status = data.status
        if (data.progress !== undefined) task.progress = data.progress
        // 完成后归档
        if (data.status === 'completed') {
          this.activeTasks = this.activeTasks.filter(t => t.id !== taskId)
          if (this.selectedTaskId === taskId) {
            this.selectTask(taskId)
          }
        }
      }
    },
    async restoreFromApi() {
      await this.fetchActive()
      // 如果有活跃任务，选中第一个
      if (this.activeTasks.length > 0 && !this.selectedTaskId) {
        await this.selectTask(this.activeTasks[0].id)
      }
    },
  },
})
```

### stores/file.js
```js
import { defineStore } from 'pinia'
import axios from 'axios'

export const useFileStore = defineStore('file', {
  state: () => ({
    files: [],
    total: 0,
    page: 1,
    pageSize: 20,
    search: '',
    statusFilter: '',
    loading: false,
  }),
  actions: {
    async fetchFiles() {
      this.loading = true
      try {
        const params = { page: this.page, size: this.pageSize }
        if (this.search) params.search = this.search
        if (this.statusFilter) params.status = this.statusFilter
        const { data } = await axios.get('/api/v1/files', { params })
        this.files = data.files || []
        this.total = data.total || 0
      } finally {
        this.loading = false
      }
    },
    downloadFile(fileId, format = 'md') {
      window.open(`/api/v1/files/${fileId}/download?format=${format}`, '_blank')
    },
    async batchDownload(fileIds) {
      const { data } = await axios.post('/api/v1/files/batch-download', { file_ids: fileIds }, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      const a = document.createElement('a')
      a.href = url; a.download = 'ocr_results.zip'; a.click()
      URL.revokeObjectURL(url)
    },
    async deleteFile(fileId) {
      await axios.delete(`/api/v1/files/${fileId}`)
      await this.fetchFiles()
    },
  },
})
```

### composables/useWebSocket.js
```js
import { ref, onMounted, onUnmounted } from 'vue'
import { useTaskStore } from '../stores/task'

export function useWebSocket() {
  const connected = ref(false)
  let ws = null
  let reconnectTimer = null

  const connect = () => {
    const sessionId = document.cookie
      .split('; ')
      .find(row => row.startsWith('paddleocr_session='))
      ?.split('=')[1]
    if (!sessionId) return

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    ws = new WebSocket(`${protocol}//${location.host}/ws/progress?session_id=${sessionId}`)

    ws.onopen = () => { connected.value = true }
    ws.onclose = () => {
      connected.value = false
      reconnectTimer = setTimeout(connect, 3000)
    }
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const taskStore = useTaskStore()
        taskStore.updateTaskProgress(data.task_id, data)
      } catch {}
    }
  }

  const disconnect = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (ws) ws.close()
  }

  onMounted(connect)
  onUnmounted(disconnect)

  return { connected, disconnect }
}
```

### utils/format.js
```js
export function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

export function statusText(s) {
  return { pending: '等待中', queued: '排队中', processing: '处理中', completed: '已完成', failed: '失败', cancelled: '已取消' }[s] || s
}

export function statusType(s) {
  return { pending: 'info', queued: 'info', processing: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }[s] || 'info'
}

export function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}
```

### router/index.js 修改
```js
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'Login', component: () => import('../views/LoginView.vue') },
  { path: '/', name: 'Main', component: () => import('../views/MainView.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, from, next) => {
  if (to.path !== '/login' && !document.cookie.includes('paddleocr_session')) {
    next('/login')
  } else {
    next()
  }
})

export default router
```

### package.json 添加依赖
```bash
cd frontend && npm install markdown-it pdfjs-dist
```

---

## Task 3: 前端 — 视图和组件

**Files:**
- Create: `frontend/src/views/MainView.vue`
- Create: `frontend/src/views/TaskWorkspace.vue`
- Create: `frontend/src/views/FileManagement.vue`
- Create: `frontend/src/views/AdminPanel.vue`
- Create: `frontend/src/components/UploadArea.vue`
- Create: `frontend/src/components/FilePreview.vue`
- Create: `frontend/src/components/TaskQueue.vue`
- Create: `frontend/src/components/MarkdownPreview.vue`
- Create: `frontend/src/components/FileTable.vue`
- Create: `frontend/src/components/AdminUserTable.vue`
- Delete: 旧视图和布局文件

### MainView.vue
```vue
<template>
  <el-container style="height: 100vh;">
    <el-header style="background: #fff; border-bottom: 1px solid #e4e7ed; display: flex; align-items: center; justify-content: space-between; padding: 0 20px;">
      <div style="display: flex; align-items: center; gap: 16px;">
        <h2 style="margin: 0; font-size: 18px; color: #303133;">PaddleOCR</h2>
        <el-tabs v-model="activeTab" style="margin-bottom: -1px;">
          <el-tab-pane label="上传任务" name="workspace" />
          <el-tab-pane label="文件管理" name="files" />
          <el-tab-pane v-if="userStore.isAdmin" label="管理后台" name="admin" />
        </el-tabs>
      </div>
      <div style="display: flex; align-items: center; gap: 12px;">
        <span style="color: #606266;">{{ userStore.displayName }}</span>
        <el-button text @click="handleLogout">退出</el-button>
      </div>
    </el-header>
    <el-main style="padding: 0; background: #f5f7fa;">
      <TaskWorkspace v-if="activeTab === 'workspace'" />
      <FileManagement v-if="activeTab === 'files'" />
      <AdminPanel v-if="activeTab === 'admin'" />
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useUserStore } from '../stores/user'
import TaskWorkspace from './TaskWorkspace.vue'
import FileManagement from './FileManagement.vue'
import AdminPanel from './AdminPanel.vue'

const userStore = useUserStore()
const router = useRouter()
const activeTab = ref('workspace')

onMounted(() => { userStore.fetchUser() })

const handleLogout = async () => {
  await axios.post('/auth/logout')
  router.push('/login')
}
</script>
```

### TaskWorkspace.vue — 左右分栏主工作区
```vue
<template>
  <div style="display: flex; height: calc(100vh - 60px);">
    <!-- 左列 -->
    <div style="flex: 1; display: flex; flex-direction: column; border-right: 1px solid #e4e7ed;">
      <div style="padding: 16px; border-bottom: 1px solid #e4e7ed;">
        <UploadArea />
      </div>
      <div style="flex: 1; overflow: auto; padding: 16px;">
        <FilePreview :preview="taskStore.selectedPreview" :task-id="taskStore.selectedTaskId" />
      </div>
    </div>
    <!-- 右列 -->
    <div style="flex: 1; display: flex; flex-direction: column;">
      <div style="padding: 16px; border-bottom: 1px solid #e4e7ed; max-height: 40%; overflow: auto;">
        <TaskQueue />
      </div>
      <div style="flex: 1; overflow: auto; padding: 16px;">
        <MarkdownPreview :result="taskStore.selectedResult" :task-id="taskStore.selectedTaskId" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useTaskStore } from '../stores/task'
import { useWebSocket } from '../composables/useWebSocket'
import UploadArea from '../components/UploadArea.vue'
import FilePreview from '../components/FilePreview.vue'
import TaskQueue from '../components/TaskQueue.vue'
import MarkdownPreview from '../components/MarkdownPreview.vue'

const taskStore = useTaskStore()
const { disconnect } = useWebSocket()

onMounted(() => { taskStore.restoreFromApi() })
</script>
```

### UploadArea.vue
```vue
<template>
  <div>
    <el-upload
      ref="uploadRef"
      drag
      multiple
      :auto-upload="false"
      :show-file-list="false"
      :on-change="handleFiles"
      accept=".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.webp,.docx,.xlsx"
    >
      <el-icon style="font-size: 40px; color: #c0c4cc;"><UploadFilled /></el-icon>
      <div>拖拽文件到此处，或 <em>点击上传</em></div>
      <template #tip>
        <div style="color: #909399; font-size: 12px; margin-top: 4px;">
          支持 PDF、图片、DOCX、XLSX，单文件最大 1GB，支持多文件
        </div>
      </template>
    </el-upload>
    <!-- 待上传文件列表 -->
    <div v-if="uploadStore.files.length" style="margin-top: 12px;">
      <div v-for="f in uploadStore.files" :key="f.id"
        style="display: flex; align-items: center; justify-content: space-between; padding: 4px 0; font-size: 13px;">
        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%;">
          {{ f.name }} ({{ formatSize(f.size) }})
        </span>
        <div style="display: flex; align-items: center; gap: 8px;">
          <el-tag v-if="f.status === 'uploading'" type="warning" size="small">上传中</el-tag>
          <el-tag v-else-if="f.status === 'done'" type="success" size="small">已提交</el-tag>
          <el-tag v-else-if="f.status === 'error'" type="danger" size="small">{{ f.errorMsg }}</el-tag>
          <el-button v-if="f.status === 'pending' || f.status === 'error'" text type="danger" size="small"
            @click="uploadStore.removeFile(f.id)">移除</el-button>
        </div>
      </div>
      <div style="margin-top: 8px; display: flex; gap: 8px;">
        <el-button type="primary" size="small" @click="uploadStore.startUpload()"
          :loading="uploadStore.uploading" :disabled="uploadStore.pendingFiles.length === 0">
          开始转换 ({{ uploadStore.pendingFiles.length }})
        </el-button>
        <el-button size="small" @click="uploadStore.clearCompleted()">清除已完成</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { UploadFilled } from '@element-plus/icons-vue'
import { useUploadStore } from '../stores/upload'
import { formatSize } from '../utils/format'

const uploadStore = useUploadStore()

const handleFiles = (uploadFile) => {
  uploadStore.addFiles([uploadFile.raw])
}
</script>
```

### FilePreview.vue
```vue
<template>
  <div style="height: 100%; display: flex; align-items: center; justify-content: center;">
    <div v-if="!preview && !taskId" style="color: #c0c4cc; text-align: center;">
      <el-icon style="font-size: 48px;"><Document /></el-icon>
      <div style="margin-top: 8px;">选择任务查看原文件</div>
    </div>
    <div v-else-if="preview?.type === 'image'" style="width: 100%; text-align: center;">
      <img :src="preview.url" style="max-width: 100%; max-height: 100%; object-fit: contain;" />
    </div>
    <div v-else-if="preview?.type === 'pdf'" style="width: 100%; height: 100%;">
      <canvas ref="pdfCanvas"></canvas>
    </div>
    <div v-else style="color: #909399;">无法预览此文件类型</div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Document } from '@element-plus/icons-vue'

const props = defineProps({ preview: Object, taskId: Number })
const pdfCanvas = ref(null)

watch(() => props.preview, async (val) => {
  if (val?.type === 'pdf' && pdfCanvas.value) {
    const pdfjsLib = await import('pdfjs-dist')
    pdfjsLib.GlobalWorkerOptions.workerSrc = ''
    const pdf = await pdfjsLib.getDocument(val.url).promise
    const page = await pdf.getPage(1)
    const viewport = page.getViewport({ scale: 1.5 })
    const canvas = pdfCanvas.value
    canvas.width = viewport.width
    canvas.height = viewport.height
    await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise
  }
}, { immediate: true })
</script>
```

### TaskQueue.vue — 虚拟滚动队列
```vue
<template>
  <div>
    <h4 style="margin: 0 0 12px;">转换队列 ({{ taskStore.activeTasks.length }})</h4>
    <div style="max-height: 300px; overflow-y: auto;">
      <div v-for="task in taskStore.activeTasks" :key="task.id"
        @click="taskStore.selectTask(task.id)"
        :style="{
          padding: '8px 12px', marginBottom: '4px', borderRadius: '4px', cursor: 'pointer',
          border: task.id === taskStore.selectedTaskId ? '2px solid #409eff' : '1px solid #ebeef5',
          background: task.id === taskStore.selectedTaskId ? '#ecf5ff' : '#fff',
        }"
      >
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <span style="font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%;">
            {{ task.input_filename }}
          </span>
          <el-tag :type="statusType(task.status)" size="small">{{ statusText(task.status) }}</el-tag>
        </div>
        <el-progress v-if="task.status === 'processing'" :percentage="task.progress" :stroke-width="4"
          style="margin-top: 4px;" />
      </div>
      <div v-if="taskStore.activeTasks.length === 0" style="color: #c0c4cc; text-align: center; padding: 20px;">
        暂无进行中的任务
      </div>
    </div>
  </div>
</template>

<script setup>
import { useTaskStore } from '../stores/task'
import { statusText, statusType } from '../utils/format'

const taskStore = useTaskStore()
</script>
```

### MarkdownPreview.vue
```vue
<template>
  <div style="height: 100%; display: flex; flex-direction: column;">
    <div v-if="taskId" style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center;">
      <el-button-group>
        <el-button :type="viewMode === 'md' ? 'primary' : ''" size="small" @click="viewMode = 'md'">Markdown</el-button>
        <el-button :type="viewMode === 'text' ? 'primary' : ''" size="small" @click="viewMode = 'text'">纯文本</el-button>
      </el-button-group>
      <el-button size="small" @click="copyResult">复制</el-button>
      <el-dropdown @command="handleDownload">
        <el-button size="small">下载<el-icon><ArrowDown /></el-icon></el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="md">Markdown</el-dropdown-item>
            <el-dropdown-item command="txt">纯文本</el-dropdown-item>
            <el-dropdown-item command="docx">DOCX</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
    <div style="flex: 1; overflow: auto; padding: 16px; background: #fff; border-radius: 4px;">
      <div v-if="!result" style="color: #c0c4cc; text-align: center; padding: 40px;">选择已完成任务查看结果</div>
      <div v-else-if="viewMode === 'md'" v-html="renderedHtml" class="markdown-body"></div>
      <pre v-else style="white-space: pre-wrap; word-break: break-word; font-size: 14px;">{{ plainText }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { ArrowDown } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'

const props = defineProps({ result: String, taskId: Number })
const viewMode = ref('md')
const md = new MarkdownIt()

const renderedHtml = computed(() => props.result ? md.render(props.result) : '')
const plainText = computed(() => props.result || '')

const copyResult = async () => {
  await navigator.clipboard.writeText(props.result || '')
  ElMessage.success('已复制')
}

const handleDownload = (format) => {
  if (props.taskId) {
    window.open(`/api/v1/files/${props.taskId}/download?format=${format}`, '_blank')
  }
}
</script>
```

### FileManagement.vue
```vue
<template>
  <div style="padding: 20px; height: 100%; display: flex; flex-direction: column;">
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
      <div style="display: flex; gap: 12px; align-items: center;">
        <el-input v-model="fileStore.search" placeholder="搜索文件名" style="width: 200px;" clearable
          @clear="fileStore.fetchFiles()" @keyup.enter="fileStore.fetchFiles()" />
        <el-select v-model="fileStore.statusFilter" placeholder="状态筛选" clearable style="width: 120px;"
          @change="fileStore.fetchFiles()">
          <el-option label="已完成" value="completed" />
          <el-option label="失败" value="failed" />
        </el-select>
      </div>
      <el-button type="primary" :disabled="selectedIds.length === 0" @click="batchDownload">
        打包下载 ({{ selectedIds.length }})
      </el-button>
    </div>
    <el-table :data="fileStore.files" stripe v-loading="fileStore.loading"
      @selection-change="handleSelectionChange" style="flex: 1;">
      <el-table-column type="selection" width="50" />
      <el-table-column prop="filename" label="文件名" min-width="200" show-overflow-tooltip />
      <el-table-column prop="file_type" label="类型" width="80" />
      <el-table-column label="大小" width="100">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <el-dropdown v-if="row.status === 'completed'" @command="(f) => fileStore.downloadFile(row.id, f)">
            <el-button text type="primary" size="small">下载</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="md">MD</el-dropdown-item>
                <el-dropdown-item command="txt">TXT</el-dropdown-item>
                <el-dropdown-item command="docx">DOCX</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <el-popconfirm title="确认删除？" @confirm="fileStore.deleteFile(row.id)">
            <template #reference>
              <el-button text type="danger" size="small">删除</el-button>
            </template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="fileStore.total > fileStore.pageSize"
      style="margin-top: 16px; justify-content: center;"
      :current-page="fileStore.page" :page-size="fileStore.pageSize"
      :total="fileStore.total" layout="prev, pager, next"
      @current-change="(p) => { fileStore.page = p; fileStore.fetchFiles() }" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useFileStore } from '../stores/file'
import { formatSize, statusText, statusType, formatTime } from '../utils/format'

const fileStore = useFileStore()
const selectedIds = ref([])

onMounted(() => { fileStore.fetchFiles() })

const handleSelectionChange = (rows) => { selectedIds.value = rows.map(r => r.id) }
const batchDownload = () => { fileStore.batchDownload(selectedIds.value) }
</script>
```

### AdminPanel.vue
```vue
<template>
  <el-tabs v-model="activeTab" style="padding: 20px;">
    <el-tab-pane label="用户管理" name="users">
      <AdminUserTable />
    </el-tab-pane>
    <el-tab-pane label="API Key 管理" name="apikeys">
      <el-card>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <h3 style="margin: 0;">API Keys</h3>
          <div style="display: flex; gap: 8px;">
            <el-input v-model="newKeyName" placeholder="Key 名称" style="width: 150px;" size="small" />
            <el-button type="primary" size="small" @click="createKey">创建</el-button>
          </div>
        </div>
        <el-table :data="apiKeys" stripe>
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="api_key" label="Key" />
          <el-table-column label="创建时间">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-popconfirm title="确认吊销此 Key？" @confirm="revokeKey(row.id)">
                <template #reference>
                  <el-button text type="danger" size="small">吊销</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import AdminUserTable from '../components/AdminUserTable.vue'
import { formatTime } from '../utils/format'

const activeTab = ref('users')
const apiKeys = ref([])
const newKeyName = ref('')

const fetchKeys = async () => {
  const { data } = await axios.get('/auth/api-keys')
  apiKeys.value = data.api_keys || []
}
const createKey = async () => {
  const { data } = await axios.post('/auth/api-keys', null, { params: { name: newKeyName.value || '默认' } })
  ElMessage.success(`Key 已创建: ${data.api_key}`)
  newKeyName.value = ''
  fetchKeys()
}
const revokeKey = async (id) => {
  await axios.delete(`/auth/api-keys/${id}`)
  ElMessage.success('已吊销')
  fetchKeys()
}

onMounted(fetchKeys)
</script>
```

### AdminUserTable.vue
```vue
<template>
  <el-table :data="users" stripe v-loading="loading">
    <el-table-column prop="id" label="ID" width="80" />
    <el-table-column prop="username" label="用户名" />
    <el-table-column prop="display_name" label="显示名" />
    <el-table-column label="角色" width="120">
      <template #default="{ row }">
        <el-tag :type="row.is_admin ? 'danger' : ''">{{ row.is_admin ? '管理员' : '用户' }}</el-tag>
      </template>
    </el-table-column>
    <el-table-column label="创建时间">
      <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
    </el-table-column>
    <el-table-column label="操作" width="120">
      <template #default="{ row }">
        <el-button text type="primary" size="small" @click="toggleAdmin(row)">
          {{ row.is_admin ? '设为用户' : '设为管理员' }}
        </el-button>
      </template>
    </el-table-column>
  </el-table>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { formatTime } from '../utils/format'

const users = ref([])
const loading = ref(false)

const fetchUsers = async () => {
  loading.value = true
  try {
    const { data } = await axios.get('/api/v1/admin/users')
    users.value = data.users || []
  } finally {
    loading.value = false
  }
}

const toggleAdmin = async (user) => {
  await axios.put(`/api/v1/admin/users/${user.id}`, { is_admin: user.is_admin ? 0 : 1 })
  ElMessage.success('已更新')
  fetchUsers()
}

onMounted(fetchUsers)
</script>
```

---

## Task 4: 收尾 — 删除旧文件 + 原文件预览 API + 构建验证

**Files:**
- Modify: `backend/api/file_router.py` — 添加预览端点
- Delete: 旧前端文件
- Build & test

### 原文件预览端点（添加到 file_router.py）
```python
@router.get("/{file_id}/preview")
async def preview_file(file_id: int, request: Request):
    """原文件预览（图片/PDF）"""
    user_id, is_admin = await _get_user_id_and_role(request)
    async with async_session() as session:
        query = select(Task).where(Task.id == file_id)
        if not is_admin:
            query = query.where(Task.user_id == user_id)
        result = await session.execute(query)
        task = result.scalar_one_or_none()
        if not task or not task.input_file_path or not os.path.exists(task.input_file_path):
            raise HTTPException(status_code=404, detail="文件不存在")

        mime = get_mime_type(task.input_filename or "")
        return FileResponse(task.input_file_path, media_type=mime)
```

### 删除旧文件
```bash
rm frontend/src/views/DashboardView.vue
rm frontend/src/views/TaskDetailView.vue
rm frontend/src/views/AdminView.vue
rm frontend/src/views/ApiDocsView.vue
rm frontend/src/layouts/MainLayout.vue
rmdir frontend/src/layouts/
```

### 安装前端依赖并构建
```bash
cd frontend && npm install && npm run build
```

### 重启后端验证
```bash
cd /opt/webapp/PaddleOCR-ui && python -m backend.main
```
