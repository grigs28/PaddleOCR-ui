<template>
  <div class="api-guide">
    <div class="guide-head">
      <div>
        <h2>API 调用说明</h2>
        <p class="sub">生产地址固定为 <code>http://192.168.0.8:5553/</code>，所有接口均基于该地址。</p>
      </div>
      <el-tag type="success" effect="light">REST API</el-tag>
    </div>

    <el-alert type="info" :closable="false" show-icon class="mb">
      <template #title>认证方式</template>
      请求头携带 <code>X-API-Key: ak_...</code>。API Key 在「管理后台 → API Key 管理」创建。
    </el-alert>

    <el-card shadow="never" class="section">
      <template #header><h3>1. 获取 API Key</h3></template>
      <ol class="steps">
        <li>使用管理员账号登录 <code>http://192.168.0.8:5553/</code></li>
        <li>进入「管理后台」→「API Key 管理」→「新建 API Key」</li>
        <li>复制生成的 <code>ak_...</code>，后续请求放在 <code>X-API-Key</code> 请求头</li>
      </ol>
      <el-alert type="warning" :closable="false" show-icon>
        文档中的 <code>ak_xxx</code> 只是占位符，请替换为你自己创建的 Key，不要泄露给他人。
      </el-alert>
    </el-card>

    <el-card shadow="never" class="section">
      <template #header><h3>2. 通用识别任务 API</h3></template>
      <p class="desc">
        支持 PDF、图片、Office 文档、DWG/DXF。提交后返回 <code>task_id</code>，通过任务详情接口轮询结果。
      </p>
      <div class="code-block">
        <div class="code-head"><span>POST /api/v1/tasks</span><el-button text size="small" @click="copy(PDF_EXAMPLE)">复制</el-button></div>
        <pre><code>{{ PDF_EXAMPLE }}</code></pre>
      </div>
      <el-table :data="taskFields" size="small" border class="mb">
        <el-table-column prop="field" label="字段" width="150" />
        <el-table-column prop="desc" label="说明" />
      </el-table>
    </el-card>

    <el-card shadow="never" class="section">
      <template #header><h3>3. DWG / DXF 图纸</h3></template>
      <el-alert type="info" :closable="false" show-icon class="mb">
        DWG/DXF 会先经 ACADxPDF 转 PDF+DXF：PDF 走识别，DXF 文字直接提取。PDF 输入 + <code>dwg</code> 则是 PDF→DWG。
      </el-alert>

      <h4>DWG → PDF + OCR（Markdown / JSON）</h4>
      <div class="code-block">
        <div class="code-head"><span>DWG 识别</span><el-button text size="small" @click="copy(DWG_OCR)">复制</el-button></div>
        <pre><code>{{ DWG_OCR }}</code></pre>
      </div>

      <h4>DWG / DXF 仅转 PDF（保留 DXF，不做 OCR）</h4>
      <div class="code-block">
        <div class="code-head"><span>仅转换</span><el-button text size="small" @click="copy(DWG_PDF_ONLY)">复制</el-button></div>
        <pre><code>{{ DWG_PDF_ONLY }}</code></pre>
      </div>

      <h4>PDF → DWG</h4>
      <div class="code-block">
        <div class="code-head"><span>PDF 转 DWG</span><el-button text size="small" @click="copy(PDF_TO_DWG)">复制</el-button></div>
        <pre><code>{{ PDF_TO_DWG }}</code></pre>
      </div>

      <h4>DXF 文字直接提取</h4>
      <div class="code-block">
        <div class="code-head"><span>DXF 提取</span><el-button text size="small" @click="copy(DXF_EXAMPLE)">复制</el-button></div>
        <pre><code>{{ DXF_EXAMPLE }}</code></pre>
      </div>

      <ul class="notes">
        <li><code>merge_pdf=true</code> 合并 DWG 多页 PDF；默认 <code>false</code>（按图框分页）。</li>
        <li>DWG/DXF 输入的 <code>output_formats=["dwg"]</code> 表示“仅转换 PDF”，不会生成 DWG 文件。</li>
        <li>PDF 输入的 <code>output_formats=["dwg"]</code> 表示 PDF→DWG。</li>
        <li>结果 ZIP 会包含转换后的 PDF、DXF 和识别结果文件。</li>
      </ul>
    </el-card>

    <el-card shadow="never" class="section">
      <template #header><h3>4. 文档转换专用 API</h3></template>

      <h4>DOCX / DOC → Markdown（同步）</h4>
      <div class="code-block">
        <div class="code-head"><span>POST /api/v1/convert/markdown</span><el-button text size="small" @click="copy(DOCX_MD)">复制</el-button></div>
        <pre><code>{{ DOCX_MD }}</code></pre>
      </div>

      <h4>PDF → Markdown（异步任务）</h4>
      <div class="code-block">
        <div class="code-head"><span>PDF 转 Markdown</span><el-button text size="small" @click="copy(PDF_MD)">复制</el-button></div>
        <pre><code>{{ PDF_MD }}</code></pre>
      </div>

      <h4>DOC → DOCX</h4>
      <div class="code-block">
        <div class="code-head"><span>POST /api/v1/convert/docx</span><el-button text size="small" @click="copy(DOC_TO_DOCX)">复制</el-button></div>
        <pre><code>{{ DOC_TO_DOCX }}</code></pre>
      </div>
    </el-card>

    <el-card shadow="never" class="section">
      <template #header><h3>5. 查询与下载</h3></template>
      <div class="code-block">
        <div class="code-head"><span>查询任务 / 下载结果</span><el-button text size="small" @click="copy(QUERY_DOWNLOAD)">复制</el-button></div>
        <pre><code>{{ QUERY_DOWNLOAD }}</code></pre>
      </div>
      <ul class="notes">
        <li><code>GET /api/v1/tasks/{id}</code> 返回 <code>result</code>（Markdown）和状态。</li>
        <li><code>GET /api/v1/files/{id}/download?format=zip</code> 下载完整结果目录。</li>
        <li><code>format</code> 可选：<code>zip</code> / <code>md</code> / <code>txt</code> / <code>json</code> / <code>docx</code>。</li>
        <li>API Key 创建的任务完成后 30 秒自动清理，请及时下载。</li>
      </ul>
    </el-card>

    <p class="footer">完整文档见仓库 <code>docs/PaddleOCR API说明文档.md</code>。</p>
  </div>
</template>

<script setup>
import { ElMessage } from 'element-plus'

const BASE = 'http://192.168.0.8:5553'

const PDF_EXAMPLE = `curl -X POST ${BASE}/api/v1/tasks \\
  -H "X-API-Key: ak_xxx" \\
  -F "file=@document.pdf" \\
  -F 'output_formats=["markdown","json"]' \\
  -F "engine=mineru"`

const DWG_OCR = `curl -X POST ${BASE}/api/v1/tasks \\
  -H "X-API-Key: ak_xxx" \\
  -F "file=@drawing.dwg" \\
  -F 'output_formats=["markdown","json"]' \\
  -F "merge_pdf=true"`

const DWG_PDF_ONLY = `curl -X POST ${BASE}/api/v1/tasks \\
  -H "X-API-Key: ak_xxx" \\
  -F "file=@drawing.dwg" \\
  -F 'output_formats=["dwg"]'`

const PDF_TO_DWG = `curl -X POST ${BASE}/api/v1/tasks \\
  -H "X-API-Key: ak_xxx" \\
  -F "file=@drawing.pdf" \\
  -F 'output_formats=["dwg"]'`

const DXF_EXAMPLE = `curl -X POST ${BASE}/api/v1/tasks \\
  -H "X-API-Key: ak_xxx" \\
  -F "file=@drawing.dxf" \\
  -F 'output_formats=["markdown","json","txt"]'`

const DOCX_MD = `curl -X POST ${BASE}/api/v1/convert/markdown \\
  -H "X-API-Key: ak_xxx" \\
  -F "file=@report.docx"`

const PDF_MD = `curl -X POST ${BASE}/api/v1/convert/markdown \\
  -H "X-API-Key: ak_xxx" \\
  -F "file=@document.pdf" \\
  -F "engine=mineru"`

const DOC_TO_DOCX = `curl -X POST ${BASE}/api/v1/convert/docx \\
  -H "X-API-Key: ak_xxx" \\
  -F "file=@old.doc" \\
  -o old.docx`

const QUERY_DOWNLOAD = `# 查询任务
curl ${BASE}/api/v1/tasks/123 \\
  -H "X-API-Key: ak_xxx"

# 下载完整结果 ZIP（含 PDF / DXF / 结果文件）
curl -L "${BASE}/api/v1/files/123/download?format=zip" \\
  -H "X-API-Key: ak_xxx" -o result.zip

# 下载 DOCX
curl -L "${BASE}/api/v1/files/123/download?format=docx" \\
  -H "X-API-Key: ak_xxx" -o result.docx`

const taskFields = [
  { field: 'file', desc: '待识别文件：pdf / 图片 / docx / doc / dwg / dxf 等' },
  { field: 'output_formats', desc: 'JSON 数组：markdown / json / txt / docx / dwg' },
  { field: 'engine', desc: 'mineru（默认）/ vl16 / ppocrv6' },
  { field: 'high_precision', desc: '仅 vl16 生效，默认 true' },
  { field: 'merge_pdf', desc: 'DWG→PDF 多页合并，默认 false' },
]

const copy = async (text) => {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
  } catch {
    ElMessage.error('复制失败，请手动选择')
  }
}
</script>

<style scoped>
.api-guide {
  height: 100%;
  overflow-y: auto;
  padding: 20px 24px 40px;
  box-sizing: border-box;
}
.guide-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.guide-head h2 {
  margin: 0 0 6px;
  font-size: 20px;
  color: #303133;
}
.sub {
  margin: 0;
  color: #606266;
  font-size: 13px;
}
.section {
  margin-bottom: 14px;
  border: 1px solid #e4e7ed;
}
.section h3 {
  margin: 0;
  font-size: 15px;
  color: #303133;
}
.section h4 {
  margin: 16px 0 8px;
  font-size: 13px;
  color: #606266;
}
.desc {
  margin: 0 0 12px;
  color: #606266;
  font-size: 13px;
}
.mb {
  margin-bottom: 12px;
}
.steps {
  margin: 0 0 12px;
  padding-left: 20px;
  color: #606266;
  line-height: 1.9;
  font-size: 13px;
}
.code-block {
  background: #1e1e1e;
  border-radius: 6px;
  margin-bottom: 12px;
  overflow: hidden;
}
.code-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 12px;
  background: #2d2d2d;
  color: #c0c4cc;
  font-size: 12px;
  font-family: Consolas, Monaco, monospace;
}
.code-block pre {
  margin: 0;
  padding: 12px 14px;
  overflow-x: auto;
}
.code-block code {
  color: #d4d4d4;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
  line-height: 1.7;
  white-space: pre;
}
.notes {
  margin: 4px 0 0;
  padding-left: 20px;
  color: #606266;
  font-size: 13px;
  line-height: 1.9;
}
.footer {
  color: #909399;
  font-size: 12px;
  text-align: center;
  margin-top: 16px;
}
code {
  background: #f4f4f5;
  padding: 1px 5px;
  border-radius: 3px;
  color: #c7254e;
  font-size: 12px;
}
</style>
