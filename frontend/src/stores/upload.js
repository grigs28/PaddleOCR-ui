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
    files: [],       // { id, raw, name, size, status, taskId, errorMsg }
    uploading: false,
    outputFormats: ['markdown', 'json'],  // 默认输出格式
  }),
  getters: {
    pendingFiles: (state) => state.files.filter(f => f.status === 'pending'),
    hasFiles: (state) => state.files.length > 0,
    availableFormats: () => [
      { value: 'markdown', label: 'Markdown' },
      { value: 'json', label: 'JSON' },
      { value: 'txt', label: '纯文本' },
      { value: 'docx', label: 'DOCX' },
    ],
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
