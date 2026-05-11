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
    mergePdf: false,
    singlePagePdf: true,  // DWG 默认单页 PDF
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
    hasPdfFiles: (state) => state.files.some(f => getFileExtension(f.name) === 'pdf'),
    hasCadFiles: (state) => state.files.some(f => {
      const ext = getFileExtension(f.name)
      return ext === 'dwg' || ext === 'dxf'
    }),
    hasMixedCadPdf: (state) => {
      const exts = new Set(state.files.map(f => getFileExtension(f.name)))
      return (exts.has('dwg') || exts.has('dxf')) && exts.has('pdf')
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
      // 添加文件后检查是否含 DWG，默认不选文字格式（只转 PDF）
      if (this.hasCadFiles) {
        // splice 清空，保证 Vue 响应式更新
        const keep = this.outputFormats.filter(f => f === 'dwg')
        this.outputFormats.splice(0, this.outputFormats.length, ...keep)
        this.singlePagePdf = true
        this.mergePdf = false
      }
    },
    removeFile(id) {
      const idx = this.files.findIndex(f => f.id === id)
      if (idx !== -1) {
        const removed = this.files.splice(idx, 1)[0]
        // 删除 CAD 文件后，若无其他 CAD 文件，恢复默认格式
        if (!this.hasCadFiles && (getFileExtension(removed.name) === 'dwg' || getFileExtension(removed.name) === 'dxf')) {
          if (this.outputFormats.length === 0) {
            this.outputFormats = ['markdown', 'json']
          }
        }
      }
    },
    async startUpload() {
      if (this.hasMixedCadPdf) {
        ElMessage.error('不能同时上传 DWG 和 PDF 文件')
        return
      }
      this.uploading = true
      const { useTaskStore } = await import('./task')
      const taskStore = useTaskStore()

      const pending = this.files.filter(f => f.status === 'pending')

      // 阶段1: 并行上传全部文件
      await Promise.all(pending.map(async (file) => {
        file.status = 'uploading'
        try {
          const formData = new FormData()
          formData.append('file', file.raw)
          formData.append('task_type', 'ocr')
          formData.append('output_formats', JSON.stringify(this.outputFormats))
          formData.append('merge_pdf', this.mergePdf ? 'true' : 'false')
          const { data } = await axios.post('/api/v1/tasks', formData)
          file.taskId = data.task_id
          file.status = 'done'
        } catch (e) {
          file.status = 'error'
          file.errorMsg = e.response?.data?.detail || '上传失败'
        }
      }))

      // 阶段2: 全部上传完成后，统一加入任务列表（触发并发处理）
      for (const file of pending.filter(f => f.status === 'done')) {
        taskStore.addActiveTask({ id: file.taskId, input_filename: file.name, input_file_size: file.size, status: 'queued', progress: 0 })
      }

      this.uploading = false
      this.files = this.files.filter(f => f.status === 'pending' || f.status === 'error')
    },
    toggleFormat(format) {
      const idx = this.outputFormats.indexOf(format)
      if (idx !== -1) {
        // 取消勾选
        this.outputFormats.splice(idx, 1)
      } else if (format === 'dwg') {
        // 勾选 DWG 时，清除其他所有格式和合并选项
        this.outputFormats = ['dwg']
        this.mergePdf = false
      } else {
        // 勾选非 DWG 格式时，移除 DWG
        this.outputFormats = this.outputFormats.filter(f => f !== 'dwg')
        this.outputFormats.push(format)
      }
    },
    clearCompleted() {
      this.files = this.files.filter(f => f.status !== 'done')
    },
  },
})
