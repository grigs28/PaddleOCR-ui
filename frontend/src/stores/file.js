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
    async batchDownload(fileIds, format = 'md') {
      const { data } = await axios.post('/api/v1/files/batch-download', { file_ids: fileIds, format }, { responseType: 'blob' })
      const url = URL.createObjectURL(data)
      const a = document.createElement('a')
      a.href = url; a.download = 'ocr_results.zip'; a.click()
      URL.revokeObjectURL(url)
    },
    async deleteFile(fileId) {
      await axios.delete(`/api/v1/files/${fileId}`)
      await this.fetchFiles()
    },
    async deleteAll() {
      await axios.delete('/api/v1/files')
      await this.fetchFiles()
    },
  },
})
