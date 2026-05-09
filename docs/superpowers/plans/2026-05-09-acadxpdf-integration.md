# ACADxPDF 集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 集成新版 ACADxPDF API（192.168.0.5:5557），实现 DWG→PDF+DXF 文字提取和 PDF→DWG 双向转换，通过输出格式勾选自动判断转换方向。

**Architecture:** 前端输出格式新增 DWG 选项，上传 PDF 时勾选 DWG 走转换路线、不勾走 OCR。后端 ACAD 客户端改为异步轮询模式适配新 API，新增 `convert_pdf_to_dwg` 函数。task_engine 根据文件类型和 output_formats 分流。

**Tech Stack:** FastAPI, Vue 3 + Element Plus, httpx (异步 HTTP), ezdxf, python-docx

---

### Task 1: DXF 控制字符清理

**Files:**
- Modify: `backend/services/export_service.py:19-34`
- Modify: `backend/services/doc_converter.py:416-541`

- [ ] **Step 1: 在 export_service.py 的 md_to_docx 中添加控制字符过滤**

```python
import re
from docx import Document
from docx.shared import Pt


def _clean_xml_text(text: str) -> str:
    """移除 XML 不兼容的控制字符（保留 \\n \\r \\t）"""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)


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
            line = _clean_xml_text(line)
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

- [ ] **Step 2: 在 doc_converter.py 的 extract_dxf_text 中清理文字内容**

在 `content = content.strip()` 之后（约第 439 行后）添加清理：

```python
        content = content.strip()
        if not content:
            continue
        # 清理 DXF 文字中的控制字符
        content = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', content)
```

文件顶部已有 `import re`（如果没有则添加）。

- [ ] **Step 3: 验证**

Run: `python3 -c "
from backend.services.doc_converter import extract_dxf_text
from backend.services.export_service import ExportService
result = extract_dxf_text('/tmp/dxf_test/公建通用设计说明（绿建篇）20241227/_input_2db528ec.dxf')
docx_bytes = ExportService.md_to_docx(result['markdown'])
print(f'DOCX {len(docx_bytes)} bytes, OK')
"`

- [ ] **Step 4: Commit**

```bash
git add backend/services/export_service.py backend/services/doc_converter.py
git commit -m "fix: 清理 DXF 文字控制字符，避免 DOCX 生成 XML 报错"
```

---

### Task 2: ACAD 客户端改造 — 异步轮询模式

**Files:**
- Modify: `backend/services/doc_converter.py:55-167`

将现有同步 `_convert_dwg_via_acad` 改为异步轮询，新增 `convert_pdf_to_dwg`。

- [ ] **Step 1: 替换 _convert_dwg_via_acad 函数**

替换 `backend/services/doc_converter.py` 中的 `_convert_dwg_via_acad` 函数（第 71-166 行）为以下内容：

```python
async def _acad_request(client: aiohttp.ClientSession, method: str, path: str, **kwargs) -> aiohttp.ClientResponse:
    """发送带认证的 ACAD API 请求"""
    settings = get_settings()
    url = settings.acad_service_url.rstrip("/") + path
    headers = kwargs.pop("headers", {})
    if settings.acad_service_apikey:
        headers["x-api-key"] = settings.acad_service_apikey
    return await client.request(method, url, headers=headers, **kwargs)


async def _poll_acad_task(client: aiohttp.ClientSession, task_path: str, task_id: str) -> dict | None:
    """轮询 ACAD 任务状态，返回完成的 task 数据或 None"""
    settings = get_settings()
    timeout = settings.libreoffice_timeout
    deadline = asyncio.get_event_loop().time() + timeout

    while asyncio.get_event_loop().time() < deadline:
        try:
            resp = await _acad_request(client, "GET", f"{task_path}/{task_id}")
            if resp.status == 200:
                data = await resp.json()
                if data.get("status") == "done":
                    return data
                if data.get("status") == "failed":
                    errors = [f["error"] for f in data.get("files", []) if f.get("error")]
                    logger.warning(f"ACAD 任务失败: {errors}")
                    return None
            await asyncio.sleep(5)
        except Exception as e:
            logger.warning(f"ACAD 轮询异常: {e}")
            await asyncio.sleep(5)
    logger.warning(f"ACAD 任务超时 ({timeout}s)")
    return None


async def _download_acad_result(task_id: str, download_path: str, output_dir: str) -> list[str]:
    """下载 ACAD 任务结果 ZIP 并解压到 output_dir，返回解压后的文件路径列表"""
    import aiohttp
    import zipfile

    async with aiohttp.ClientSession() as client:
        resp = await _acad_request(client, "GET", f"{download_path}/{task_id}")
        if resp.status != 200:
            logger.warning(f"ACAD 下载失败: {resp.status}")
            return []
        zip_bytes = await resp.read()

    if not zip_bytes:
        return []

    # 解压
    temp_extract = os.path.join(output_dir, f"_acad_temp_{task_id[:8]}")
    os.makedirs(temp_extract, exist_ok=True)
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            zf.extractall(temp_extract)
        result_files = []
        for root, dirs, files in os.walk(temp_extract):
            for f in files:
                result_files.append(os.path.join(root, f))
        return result_files
    except Exception as e:
        logger.warning(f"ACAD 解压失败: {e}")
        shutil.rmtree(temp_extract, ignore_errors=True)
        return []


async def _convert_dwg_via_acad(input_path: str, output_dir: str) -> str | None:
    """通过 ACADxPDF 服务将 DWG 转 PDF+DXF（异步轮询模式）。
    返回合并后的 PDF 路径，DXF 保存在同目录。
    """
    import aiohttp

    settings = get_settings()
    acad_url = settings.acad_service_url.rstrip("/")

    # 先检查服务是否可用
    try:
        async with aiohttp.ClientSession() as client:
            resp = await _acad_request(client, "GET", "/health")
            if resp.status != 200:
                return None
    except Exception:
        return None

    # 提交转换任务
    try:
        async with aiohttp.ClientSession() as client:
            with open(input_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("files", f, filename=os.path.basename(input_path))
                resp = await _acad_request(client, "POST", "/convert", data=data,
                                           timeout=aiohttp.ClientTimeout(total=30))
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(f"ACAD 提交失败 {resp.status}: {text[:200]}")
                    return None
                result = await resp.json()
                task_id = result.get("task_id")
                if not task_id:
                    return None
    except Exception as e:
        logger.warning(f"ACAD 提交异常: {e}")
        return None

    # 轮询任务状态
    async with aiohttp.ClientSession() as client:
        task_data = await _poll_acad_task(client, "/tasks", task_id)
    if not task_data:
        return None

    # 下载结果
    extracted = await _download_acad_result(task_id, "/download", output_dir)
    if not extracted:
        return None

    # 分类文件：PDF、DXF、DWG
    pdf_files = []
    dxf_files = []
    for f in extracted:
        lower = f.lower()
        if lower.endswith(".pdf"):
            pdf_files.append(f)
        elif lower.endswith(".dxf"):
            dxf_files.append(f)

    # 移动 DXF 到 output_dir
    for dxf in dxf_files:
        dxf_dest = os.path.join(output_dir, os.path.basename(dxf))
        if not os.path.exists(dxf_dest):
            shutil.move(dxf, dxf_dest)
            logger.info(f"DXF 已保存: {dxf_dest}")

    if not pdf_files:
        shutil.rmtree(os.path.dirname(extracted[0]), ignore_errors=True)
        return None

    # 移动 PDF 到 output_dir
    saved_pdfs = []
    for pdf in pdf_files:
        dest = os.path.join(output_dir, os.path.basename(pdf))
        if not os.path.exists(dest):
            shutil.copy2(pdf, dest)
        saved_pdfs.append(dest)

    base = os.path.splitext(os.path.basename(input_path))[0]

    if len(saved_pdfs) == 1:
        final_path = saved_pdfs[0]
        shutil.rmtree(os.path.dirname(extracted[0]), ignore_errors=True)
        logger.info(f"ACAD 转换成功（单页）: {final_path}")
        return final_path

    # 多页合并
    final_path = os.path.join(output_dir, f"{base}.pdf")
    await _merge_pdfs(saved_pdfs, final_path)
    shutil.rmtree(os.path.dirname(extracted[0]), ignore_errors=True)
    logger.info(f"ACAD 转换成功（{len(pdf_files)} 页合并）: {final_path}")
    return final_path


async def convert_pdf_to_dwg(input_path: str, output_dir: str) -> str | None:
    """通过 ACADxPDF 服务将 PDF 转 DWG（异步轮询模式）。
    返回 DWG 文件路径，失败返回 None。
    """
    import aiohttp

    settings = get_settings()

    # 检查服务
    try:
        async with aiohttp.ClientSession() as client:
            resp = await _acad_request(client, "GET", "/health")
            if resp.status != 200:
                return None
    except Exception:
        return None

    # 提交 PDF→DWG 任务
    try:
        async with aiohttp.ClientSession() as client:
            with open(input_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("files", f, filename=os.path.basename(input_path))
                resp = await _acad_request(client, "POST", "/convert-pdf", data=data,
                                           timeout=aiohttp.ClientTimeout(total=30))
                if resp.status != 200:
                    text = await resp.text()
                    logger.warning(f"ACAD PDF→DWG 提交失败 {resp.status}: {text[:200]}")
                    return None
                result = await resp.json()
                task_id = result.get("task_id")
                if not task_id:
                    return None
    except Exception as e:
        logger.warning(f"ACAD PDF→DWG 提交异常: {e}")
        return None

    # 轮询
    async with aiohttp.ClientSession() as client:
        task_data = await _poll_acad_task(client, "/pdf-task", task_id)
    if not task_data:
        return None

    # 下载结果
    extracted = await _download_acad_result(task_id, "/download-pdf-zip", output_dir)
    if not extracted:
        return None

    # 找 DWG 文件
    dwg_files = [f for f in extracted if f.lower().endswith(".dwg")]
    if not dwg_files:
        logger.warning("PDF→DWG 结果中无 DWG 文件")
        shutil.rmtree(os.path.dirname(extracted[0]), ignore_errors=True)
        return None

    # 移动 DWG 到 output_dir
    dwg_dest = os.path.join(output_dir, os.path.basename(dwg_files[0]))
    shutil.copy2(dwg_files[0], dwg_dest)
    shutil.rmtree(os.path.dirname(extracted[0]), ignore_errors=True)
    logger.info(f"PDF→DWG 转换成功: {dwg_dest}")
    return dwg_dest
```

注意保留原有的 `import re`，并在文件顶部 import 区域确认已有 `import io`、`import zipfile`、`import aiohttp`（在函数内 import 的不动）。

- [ ] **Step 2: 更新 convert_dwg_to_pdf 的导入**

在 `task_engine.py` 的 import 中添加 `convert_pdf_to_dwg`：

```python
from backend.services.doc_converter import (
    is_libreoffice_available, convert_to_pdf, is_legacy_office,
    extract_docx_text, extract_xlsx_text,
    is_cad2x_available, convert_dwg_to_pdf,
    extract_dxf_text, convert_pdf_to_dwg,
)
```

- [ ] **Step 3: 验证语法**

Run: `python3 -c "from backend.services.doc_converter import convert_dwg_to_pdf, convert_pdf_to_dwg; print('OK')"`

- [ ] **Step 4: Commit**

```bash
git add backend/services/doc_converter.py
git commit -m "feat: ACAD 客户端改为异步轮询模式，新增 PDF→DWG 转换"
```

---

### Task 3: task_engine 新增 PDF→DWG 分支

**Files:**
- Modify: `backend/services/task_engine.py:193-197`

- [ ] **Step 1: 修改 PDF 处理分支**

将 `task_engine.py` 第 193-197 行的 PDF 分支替换为：

```python
                    elif is_pdf_file(filename):
                        # PDF: 根据 output_formats 判断走 OCR 还是转 DWG
                        output_formats = []
                        try:
                            output_formats = json.loads(task.output_formats or '["markdown"]')
                        except Exception:
                            output_formats = ["markdown"]

                        if 'dwg' in output_formats:
                            # PDF→DWG 纯转换
                            dwg_path = await convert_pdf_to_dwg(file_path, os.path.dirname(file_path))
                            if not dwg_path:
                                await self._update_status(task_id, "failed", error="PDF→DWG 转换失败")
                                return

                            # 直接保存 DWG 结果，不走 OCR
                            progress_loop.cancel()
                            try:
                                await progress_loop
                            except asyncio.CancelledError:
                                pass

                            result_dir = get_result_path(str(task_id))
                            source_dest = os.path.join(result_dir, f"source_{filename}")
                            shutil.copy2(file_path, source_dest)
                            dwg_dest = os.path.join(result_dir, os.path.basename(dwg_path))
                            shutil.copy2(dwg_path, dwg_dest)

                            processing_seconds = int(time.monotonic() - wall_start)
                            completed_at = datetime.now()
                            async with async_session() as s:
                                await s.execute(
                                    update(Task)
                                    .where(Task.id == task_id)
                                    .values(
                                        result_path=result_dir,
                                        progress=100,
                                        page_total=1,
                                        page_current=1,
                                        processing_time=processing_seconds,
                                        completed_at=completed_at,
                                        status="completed",
                                    )
                                )
                                await s.commit()
                            logger.info(f"任务 {task_id} PDF→DWG 完成, 用时{processing_seconds}秒")
                            return
                        else:
                            ocr_result = await ocr_client.recognize_pdf(file_path)
```

- [ ] **Step 2: 验证语法**

Run: `python3 -c "from backend.services.task_engine import task_engine; print('OK')"`

- [ ] **Step 3: Commit**

```bash
git add backend/services/task_engine.py
git commit -m "feat: task_engine 新增 PDF→DWG 分支"
```

---

### Task 4: 前端 — 输出格式新增 DWG + 条件显示 + 混合校验

**Files:**
- Modify: `frontend/src/stores/upload.js:19-30,58-80`
- Modify: `frontend/src/components/UploadArea.vue:20-27`

- [ ] **Step 1: upload.js — 添加 DWG 格式 + 辅助方法**

替换 `upload.js` 的 state/getters/actions：

```javascript
import { defineStore } from 'pinia'
import axios from 'axios'
import { ElMessage } from 'element-plus'

const MAX_FILE_SIZE = 1024 * 1024 * 1024 // 1GB
const ALLOWED_EXTENSIONS = new Set(['pdf', 'jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp', 'doc', 'docx', 'odt', 'rtf', 'xls', 'xlsx', 'ods', 'csv', 'ppt', 'pptx', 'odp', 'txt', 'html', 'htm', 'dwg', 'dxf'])

function getFileExtension(filename) {
  const dot = filename.lastIndexOf('.')
  if (dot === -1) return ''
  return filename.slice(dot + 1).toLowerCase()
}

export const useUploadStore = defineStore('upload', {
  state: () => ({
    files: [],
    uploading: false,
    outputFormats: ['markdown', 'json'],
  }),
  getters: {
    pendingFiles: (state) => state.files.filter(f => f.status === 'pending'),
    hasFiles: (state) => state.files.length > 0,
    availableFormats: () => [
      { value: 'markdown', label: 'Markdown' },
      { value: 'json', label: 'JSON' },
      { value: 'txt', label: '纯文本' },
      { value: 'docx', label: 'DOCX' },
      { value: 'dwg', label: 'DWG', pdfOnly: true },
    ],
    hasPdfFiles: (state) => state.files.some(f => {
      const ext = getFileExtension(f.name)
      return ext === 'pdf'
    }),
    hasCadFiles: (state) => state.files.some(f => {
      const ext = getFileExtension(f.name)
      return ext === 'dwg' || ext === 'dxf'
    }),
    hasMixedCadPdf: (state) => {
      const exts = new Set(state.files.map(f => getFileExtension(f.name)))
      const hasCad = exts.has('dwg') || exts.has('dxf')
      const hasPdf = exts.has('pdf')
      return hasCad && hasPdf
    },
  },
  actions: {
    addFiles(fileList) {
      for (const file of fileList) {
        const ext = getFileExtension(file.name)
        if (!ALLOWED_EXTENSIONS.has(ext)) {
          ElMessage.warning(`不支持的文件类型: ${file.name}，仅支持 PDF/图片/Office文档`)
          continue
        }
        if (file.size > MAX_FILE_SIZE) {
          ElMessage.warning(`文件 ${file.name} 超过 1GB 限制`)
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
      // 混合校验：DWG 和 PDF 不能同时上传
      if (this.hasMixedCadPdf) {
        ElMessage.error('不能同时上传 DWG 和 PDF 文件')
        return
      }
      this.uploading = true
      const { useTaskStore } = await import('./task')
      const taskStore = useTaskStore()

      for (const file of this.files.filter(f => f.status === 'pending')) {
        file.status = 'uploading'
        try {
          const formData = new FormData()
          formData.append('file', file.raw)
          formData.append('task_type', 'ocr')
          formData.append('output_formats', JSON.stringify(this.outputFormats))
          const { data } = await axios.post('/api/v1/tasks', formData)
          file.taskId = data.task_id
          file.status = 'done'
          taskStore.addActiveTask({ id: data.task_id, input_filename: file.name, input_file_size: file.size, status: 'queued', progress: 0 })
        } catch (e) {
          file.status = 'error'
          file.errorMsg = e.response?.data?.detail || '上传失败'
        }
      }
      this.uploading = false
      this.files = this.files.filter(f => f.status === 'pending' || f.status === 'error')
    },
    clearCompleted() {
      this.files = this.files.filter(f => f.status !== 'done')
    },
  },
})
```

- [ ] **Step 2: UploadArea.vue — 条件显示 DWG 格式**

替换输出格式选择部分（第 20-27 行）：

```html
    <!-- 输出格式选择 -->
    <div style="margin-top: 8px; display: flex; align-items: center; gap: 8px;">
      <span style="font-size: 12px; color: #909399;">输出格式：</span>
      <el-checkbox-group v-model="uploadStore.outputFormats" size="small">
        <el-checkbox v-for="fmt in uploadStore.availableFormats" :key="fmt.value"
          :label="fmt.value" v-show="!fmt.pdfOnly || uploadStore.hasPdfFiles">{{ fmt.label }}</el-checkbox>
      </el-checkbox-group>
    </div>
    <div v-if="uploadStore.hasMixedCadPdf" style="margin-top: 4px; color: #f56c6c; font-size: 12px;">
      不能同时上传 DWG 和 PDF 文件
    </div>
```

同时更新"开始转换"按钮，增加混合校验禁用：

```html
        <el-button type="primary" size="small" @click="uploadStore.startUpload()"
          :loading="uploadStore.uploading"
          :disabled="uploadStore.pendingFiles.length === 0 || uploadStore.outputFormats.length === 0 || uploadStore.hasMixedCadPdf">
          开始转换 ({{ uploadStore.pendingFiles.length }})
        </el-button>
```

- [ ] **Step 3: 构建前端**

Run: `cd frontend && npm run build && cp -r dist/* ../static/`

- [ ] **Step 4: Commit**

```bash
git add frontend/src/stores/upload.js frontend/src/components/UploadArea.vue
git commit -m "feat: 前端输出格式新增 DWG，PDF/DWG 混合上传校验"
```

---

### Task 5: 配置更新 + 测试

**Files:**
- Modify: `backend/config.py:23`

- [ ] **Step 1: 更新 ACAD 服务默认地址**

```python
    # ACAD DWG 转 PDF 服务配置
    acad_service_url: str = "http://192.168.0.5:5557"
    acad_service_apikey: str = ""
```

- [ ] **Step 2: 更新 .env 文件**

```bash
# 在 .env 中更新
ACAD_SERVICE_URL=http://192.168.0.5:5557
ACAD_SERVICE_APIKEY=axp-8fc2a57f4fccf5a561acab20588ae533
```

- [ ] **Step 3: 重启后端验证**

Run: `pkill -f "uvicorn backend.main"; sleep 1; nohup python3 -m uvicorn backend.main:app --host 0.0.0.0 --port 5553 > /tmp/ocr_ui.log 2>&1 &`

验证：上传 DWG 文件确认 DXF 文字提取正常，上传 PDF 勾选 DWG 确认转换正常。

- [ ] **Step 4: Commit**

```bash
git add backend/config.py .gitignore docs/
git commit -m "feat: ACAD 服务配置更新为 192.168.0.5:5557"
```

---

### Task 6: Docker 构建 + 推送 08

**Files:** 无代码改动

- [ ] **Step 1: 本地构建镜像**

Run: `cd /opt/webapp/PaddleOCR-ui && docker build -t paddleocr-ui -f docker/Dockerfile .`

- [ ] **Step 2: 导出并推送到 08**

Run: `docker save paddleocr-ui:latest | gzip > /tmp/paddleocr-ui.tar.gz`

Run: `export SSHPASS='Slnwg123$' && sshpass -e scp /tmp/paddleocr-ui.tar.gz grigs@192.168.0.8:/tmp/`

- [ ] **Step 3: 替换 08 容器**

```bash
export SSHPASS='Slnwg123$'
sshpass -e ssh grigs@192.168.0.8 "
echo 'Slnwg123$' | sudo -S docker stop paddleocr-ui
echo 'Slnwg123$' | sudo -S docker rm paddleocr-ui
echo 'Slnwg123$' | sudo -S docker load -i /tmp/paddleocr-ui.tar.gz
echo 'Slnwg123$' | sudo -S docker run -d --name paddleocr-ui --restart unless-stopped -p 5553:5553 -v /opt/webapp/PaddleOCR-ui/docker/data:/app/data --env-file /opt/webapp/PaddleOCR-ui/.env paddleocr-ui:latest
"
```

- [ ] **Step 4: 更新 08 的 .env 配置**

```bash
export SSHPASS='Slnwg123$'
sshpass -e ssh grigs@192.168.0.8 "
cat > /opt/webapp/PaddleOCR-ui/.env << 'ENVEOF'
DB_HOST=192.168.0.98
DB_PORT=5432
DB_USER=grigs
DB_PASSWORD=Slnwg123\$
DB_NAME=paddleocr_ui
OCR_SERVICE_URL=http://192.168.0.70:5564
ACAD_SERVICE_URL=http://192.168.0.5:5557
ACAD_SERVICE_APIKEY=axp-8fc2a57f4fccf5a561acab20588ae533
YZ_LOGIN_URL=http://192.168.0.18:5551
CALLBACK_URL=http://192.168.0.8:5553/auth/callback
APP_HOST=0.0.0.0
APP_PORT=5553
SECRET_KEY=change-this-in-production
UPLOAD_DIR=data/uploads
RESULT_DIR=data/results
TEMP_DIR=data/temp
MAX_FILE_SIZE_MB=1024
ocr_image_timeout=300
admin_usernames=admin,grigs
ENVEOF
"
```

重启容器使新 .env 生效。
