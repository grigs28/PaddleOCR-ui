<template>
  <div style="height: 100%; display: flex; flex-direction: column;">
    <div v-if="taskId" style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center;">
      <el-button-group>
        <el-button :type="viewMode === 'md' ? 'primary' : ''" size="small" @click="viewMode = 'md'">Markdown</el-button>
        <el-button :type="viewMode === 'text' ? 'primary' : ''" size="small" @click="viewMode = 'text'">纯文本</el-button>
      </el-button-group>
      <el-button size="small" @click="copyResult">复制</el-button>
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
