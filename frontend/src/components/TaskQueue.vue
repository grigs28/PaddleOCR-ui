<template>
  <div>
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
      <h4 style="margin: 0;">转换队列 ({{ taskStore.sortedTasks.length }})</h4>
      <div style="display: flex; gap: 8px;">
        <el-button size="small" @click="toggleSelectAll" :disabled="allTasks.length === 0">
          {{ allSelected ? '取消全选' : '全选' }}
        </el-button>
        <el-button type="primary" size="small" :disabled="selectedIds.length === 0"
          @click="batchDownload">打包下载 ({{ selectedIds.length }})</el-button>
        <el-button type="danger" size="small" :disabled="selectedIds.length === 0"
          @click="batchDelete">删除选中 ({{ selectedIds.length }})</el-button>
      </div>
    </div>
    <div style="max-height: 300px; overflow-y: auto;">
      <div v-for="task in taskStore.sortedTasks" :key="task.id"
        @click="taskStore.selectTask(task.id)"
        :style="{
          padding: '8px 12px', marginBottom: '4px', borderRadius: '4px', cursor: 'pointer',
          border: task.id === taskStore.selectedTaskId ? '2px solid #409eff' : '1px solid #ebeef5',
          background: task.id === taskStore.selectedTaskId ? '#ecf5ff' : '#fff',
        }"
      >
        <div style="display: flex; justify-content: space-between; align-items: center;">
          <div style="display: flex; align-items: center; gap: 8px; min-width: 0; flex: 1;">
            <el-checkbox
              :model-value="selectedIds.includes(task.id)"
              @change="(v) => toggleSelect(task.id, v)"
              @click.stop
              size="small"
            />
            <span style="font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
              {{ task.input_filename }}
            </span>
          </div>
          <div style="display: flex; align-items: center; gap: 6px; flex-shrink: 0;">
            <span v-if="task.processing_time" style="font-size: 11px; color: #909399;">
              {{ formatDuration(task.processing_time) }}
            </span>
            <el-tag :type="statusType(task.status)" size="small">{{ statusText(task.status) }}</el-tag>
            <el-button text type="danger" size="small" @click.stop="deleteOne(task.id)"
              :disabled="task.status === 'processing'" title="删除">
              <el-icon><Delete /></el-icon>
            </el-button>
          </div>
        </div>
        <el-progress v-if="task.status === 'processing'" :percentage="task.progress" :stroke-width="4"
          :format="() => phaseText(task)" style="margin-top: 4px;" />
      </div>
      <div v-if="taskStore.sortedTasks.length === 0" style="color: #c0c4cc; text-align: center; padding: 20px;">
        暂无任务
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import { useTaskStore } from '../stores/task'
import { useFileStore } from '../stores/file'
import { statusText, statusType } from '../utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const taskStore = useTaskStore()
const fileStore = useFileStore()
const selectedIds = ref([])

const allTasks = computed(() => taskStore.sortedTasks)
const allSelected = computed(() =>
  allTasks.value.length > 0 && allTasks.value.every(t => selectedIds.value.includes(t.id))
)

const toggleSelect = (id, checked) => {
  if (checked) {
    if (!selectedIds.value.includes(id)) selectedIds.value.push(id)
  } else {
    selectedIds.value = selectedIds.value.filter(i => i !== id)
  }
}

const toggleSelectAll = () => {
  if (allSelected.value) {
    selectedIds.value = []
  } else {
    selectedIds.value = allTasks.value.map(t => t.id)
  }
}

const deleteOne = async (id) => {
  await ElMessageBox.confirm('确认删除？', '提示', { type: 'warning' })
  try {
    await axios.delete(`/api/v1/files/${id}`)
  } catch {}
  taskStore.removeTask(id)
  selectedIds.value = selectedIds.value.filter(i => i !== id)
  ElMessage.success('已删除')
}

const batchDelete = async () => {
  await ElMessageBox.confirm(`确认删除 ${selectedIds.value.length} 个任务？`, '批量删除', { type: 'warning' })
  for (const id of selectedIds.value) {
    try { await axios.delete(`/api/v1/files/${id}`) } catch {}
    taskStore.removeTask(id)
  }
  selectedIds.value = []
  ElMessage.success('已删除')
}

const batchDownload = () => { fileStore.batchDownload(selectedIds.value) }

const formatDuration = (seconds) => {
  if (!seconds) return ''
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m > 0 ? `${m}分${s}秒` : `${s}秒`
}

const phaseText = (task) => {
  if (task.phase === 'converting') return `转换PDF ${task.progress}%`
  if (task.phase === 'ocr') return `OCR识别 ${task.progress}%`
  return `${task.progress}%`
}
</script>
