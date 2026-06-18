<template>
  <div style="height: 100%; display: flex; flex-direction: column;">
    <div v-if="taskId" style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center;">
      <el-button-group>
        <el-button :type="viewMode === 'md' ? 'primary' : ''" size="small" @click="viewMode = 'md'">Markdown</el-button>
        <el-button v-if="ppocrData" :type="viewMode === 'visual' ? 'primary' : ''" size="small" @click="viewMode = 'visual'">可视化</el-button>
        <el-button :type="viewMode === 'text' ? 'primary' : ''" size="small" @click="viewMode = 'text'">纯文本</el-button>
        <el-button v-if="resultJson" :type="viewMode === 'json' ? 'primary' : ''" size="small" @click="viewMode = 'json'">JSON</el-button>
      </el-button-group>
      <el-button size="small" @click="copyResult">复制</el-button>
    </div>
    <!-- PP-OCRv6 可视化模式 -->
    <div v-if="viewMode === 'visual' && ppocrData" style="flex: 1;">
      <PPOCRPreview :ocrData="ppocrData" />
    </div>
    <!-- Markdown / 纯文本模式 -->
    <div v-else style="flex: 1; overflow: auto; padding: 16px; background: #fff; border-radius: 4px;">
      <div v-if="!result" style="color: #c0c4cc; text-align: center; padding: 40px;">选择已完成任务查看结果</div>
      <div v-else-if="viewMode === 'md'" v-html="renderedHtml" class="markdown-body" style="word-break: break-word; overflow-wrap: break-word;"></div>
      <pre v-else-if="viewMode === 'json'" style="white-space: pre-wrap; word-break: break-word; font-size: 13px;">{{ formattedJson }}</pre>
      <pre v-else style="white-space: pre-wrap; word-break: break-word; font-size: 14px;">{{ plainText }}</pre>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import MarkdownIt from 'markdown-it'
import PPOCRPreview from './PPOCRPreview.vue'

const props = defineProps({ result: String, resultJson: String, taskId: Number, ppocrData: { type: Array, default: null } })
const viewMode = ref(props.ppocrData ? 'visual' : 'md')
const md = new MarkdownIt({ html: true, linkify: true, breaks: true }).enable('table')

const renderedHtml = computed(() => props.result ? md.render(props.result) : '')
const plainText = computed(() => props.result || '')
const formattedJson = computed(() => {
  if (!props.resultJson) return ''
  try { return JSON.stringify(JSON.parse(props.resultJson), null, 2) }
  catch { return props.resultJson }
})

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

<style scoped>
.markdown-body {
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
}
.markdown-body h1 { font-size: 22px; margin: 20px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #e4e7ed; }
.markdown-body h2 { font-size: 18px; margin: 18px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #ebeef5; }
.markdown-body h3 { font-size: 16px; margin: 14px 0 6px; }
.markdown-body h4, .markdown-body h5, .markdown-body h6 { font-size: 14px; margin: 10px 0 4px; }
.markdown-body p { margin: 8px 0; }
.markdown-body ul, .markdown-body ol { padding-left: 24px; margin: 8px 0; }
.markdown-body li { margin: 4px 0; }
.markdown-body blockquote { margin: 8px 0; padding: 8px 16px; border-left: 4px solid #dcdfe6; background: #f5f7fa; color: #606266; }
.markdown-body code { background: #f5f7fa; padding: 2px 6px; border-radius: 3px; font-size: 13px; color: #e96900; }
.markdown-body pre { background: #fafafa; padding: 12px; border-radius: 4px; overflow-x: auto; margin: 8px 0; }
.markdown-body pre code { background: none; padding: 0; color: inherit; }
.markdown-body img { max-width: 100%; height: auto; margin: 8px 0; }
.markdown-body hr { border: none; border-top: 1px solid #e4e7ed; margin: 16px 0; }
/* 表格样式 — 单线 */
.markdown-body table {
  width: 100%;
  border-collapse: collapse;
  border: none;
  margin: 12px 0;
  font-size: 13px;
  table-layout: auto;
}
.markdown-body table th,
.markdown-body table td {
  border: 1px solid #dcdfe6;
  padding: 8px 12px;
  text-align: left;
  vertical-align: top;
  word-break: break-word;
}
.markdown-body table th {
  background: #f5f7fa;
  font-weight: 600;
  color: #303133;
}
.markdown-body table tr:hover td {
  background: #f5f7fa;
}
.markdown-body table tr:nth-child(even) td {
  background: #fafafa;
}
.markdown-body table tr:nth-child(even):hover td {
  background: #f5f7fa;
}
/* HPS 返回的内联样式表格也做兜底 */
.markdown-body table td[style*="text-align: center"] {
  text-align: center;
}
</style>
