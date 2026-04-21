import { defineStore } from 'pinia'
import axios from 'axios'

// 排序权重：处理中 > 排队中 > 等待中 > 已完成/失败
const STATUS_ORDER = {
  processing: 0,
  queued: 1,
  pending: 2,
  completed: 3,
  failed: 4,
  cancelled: 5,
}

function sortTasks(tasks) {
  return [...tasks].sort((a, b) => {
    const wa = STATUS_ORDER[a.status] ?? 9
    const wb = STATUS_ORDER[b.status] ?? 9
    if (wa !== wb) return wa - wb
    // 同状态按创建时间倒序
    return new Date(b.created_at || 0) - new Date(a.created_at || 0)
  })
}

export const useTaskStore = defineStore('task', {
  state: () => ({
    activeTasks: [],     // 所有任务（含已完成，不清空）
    selectedTaskId: null,
    selectedResult: '',
    selectedPreview: null,  // { url, type: 'pdf'|'image' }
  }),
  getters: {
    sortedTasks: (state) => sortTasks(state.activeTasks),
  },
  actions: {
    async fetchActive() {
      const { data } = await axios.get('/api/v1/tasks')
      this.activeTasks = sortTasks(data.tasks || [])
    },
    addActiveTask(task) {
      this.activeTasks.push(task)
      this.activeTasks = sortTasks(this.activeTasks)
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
        const task = data.task || data
        if (task.input_filename) {
          const ext = task.input_filename.split('.').pop().toLowerCase()
          if (['pdf'].includes(ext)) {
            this.selectedPreview = { url: `/api/v1/files/${taskId}/preview`, type: 'pdf' }
          } else if (['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'webp'].includes(ext)) {
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
        if (data.phase !== undefined) task.phase = data.phase
        if (data.processing_time !== undefined) task.processing_time = data.processing_time
        // 完成时更新结果，但不清除
        if (data.status === 'completed' || data.status === 'failed') {
          if (data.processing_time) task.processing_time = data.processing_time
          if (this.selectedTaskId === taskId) {
            this.selectTask(taskId)
          }
        }
        // 被取消/删除时从队列移除
        if (data.status === 'cancelled') {
          this.activeTasks = this.activeTasks.filter(t => t.id !== taskId)
          if (this.selectedTaskId === taskId) {
            this.selectedTaskId = null
            this.selectedResult = ''
            this.selectedPreview = null
          }
          return
        }
      }
      // 重新排序
      this.activeTasks = sortTasks(this.activeTasks)
    },
    removeTask(taskId) {
      this.activeTasks = this.activeTasks.filter(t => t.id !== taskId)
      if (this.selectedTaskId === taskId) {
        this.selectedTaskId = null
        this.selectedResult = ''
        this.selectedPreview = null
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
