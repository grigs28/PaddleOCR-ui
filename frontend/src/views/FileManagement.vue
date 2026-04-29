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
      <div style="display: flex; gap: 8px;">
        <el-button @click="downloadAll" :disabled="completedCount === 0">下载全部</el-button>
        <el-button type="primary" :disabled="selectedIds.length === 0" @click="batchDownload">
          打包下载 ({{ selectedIds.length }})
        </el-button>
        <el-button type="danger" :disabled="selectedIds.length === 0" @click="batchDelete">
          删除选中 ({{ selectedIds.length }})
        </el-button>
        <el-button type="danger" plain @click="deleteAll" :disabled="fileStore.total === 0">全部删除</el-button>
      </div>
    </div>
    <el-table :data="fileStore.files" v-loading="fileStore.loading"
      @selection-change="handleSelectionChange" style="flex: 1;"
      :row-class-name="rowClassName">
      <el-table-column type="selection" width="50" :selectable="(row) => row.deleted !== 2" />
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
      <el-table-column v-if="showUserCol" prop="username" label="用户" width="120" />
      <el-table-column label="用时" width="100">
        <template #default="{ row }">
          <span v-if="row.processing_time" style="font-size: 12px; color: #909399;">
            {{ formatDuration(row.processing_time) }}
          </span>
          <span v-else style="color: #c0c4cc;">-</span>
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="170">
        <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200">
        <template #default="{ row }">
          <template v-if="row.deleted === 1">
            <el-tag type="info" size="small">已删除</el-tag>
          </template>
          <template v-else>
            <el-dropdown v-if="row.status === 'completed'" @command="(f) => fileStore.downloadFile(row.id, f)">
              <el-button text type="primary" size="small">下载</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="md">MD</el-dropdown-item>
                  <el-dropdown-item command="txt">TXT</el-dropdown-item>
                  <el-dropdown-item command="docx">DOCX</el-dropdown-item>
                  <el-dropdown-item command="json">JSON</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-popconfirm :title="isAdmin ? '管理员彻底删除，不可恢复，确认？' : '确认删除？'" @confirm="deleteOne(row.id)">
              <template #reference>
                <el-button text type="danger" size="small">{{ isAdmin ? '彻底删除' : '删除' }}</el-button>
              </template>
            </el-popconfirm>
          </template>
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
import { ref, computed, onMounted } from 'vue'
import { useFileStore } from '../stores/file'
import { useTaskStore } from '../stores/task'
import { useUserStore } from '../stores/user'
import { formatSize, statusText, statusType, formatTime } from '../utils/format'
import { ElMessage, ElMessageBox } from 'element-plus'

const fileStore = useFileStore()
const taskStore = useTaskStore()
const userStore = useUserStore()
const selectedIds = ref([])

const isAdmin = computed(() => userStore.isAdmin)
const showUserCol = computed(() => isAdmin.value)
const completedCount = computed(() => fileStore.files.filter(f => f.status === 'completed' && f.deleted !== 1).length)

onMounted(() => { fileStore.fetchFiles() })

const rowClassName = ({ row }) => row.deleted === 1 ? 'soft-deleted-row' : ''

const handleSelectionChange = (rows) => { selectedIds.value = rows.map(r => r.id) }

const deleteOne = async (id) => {
  await fileStore.deleteFile(id)
  taskStore.removeTask(id)
}

const batchDownload = () => { fileStore.batchDownload(selectedIds.value) }
const downloadAll = () => {
  const ids = fileStore.files.filter(f => f.status === 'completed' && f.deleted !== 1).map(f => f.id)
  fileStore.batchDownload(ids)
}

const batchDelete = async () => {
  for (const id of selectedIds.value) {
    await fileStore.deleteFile(id)
    taskStore.removeTask(id)
  }
  selectedIds.value = []
  ElMessage.success(isAdmin.value ? '已彻底删除' : '已删除')
}

const deleteAll = async () => {
  await ElMessageBox.confirm(
    isAdmin.value ? '确认删除所有文件？管理员操作将彻底删除，不可恢复！' : '确认删除所有文件？',
    '全部删除',
    { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
  )
  await fileStore.deleteAll()
  taskStore.clearTasks()
  ElMessage.success('已全部删除')
}

const formatDuration = (seconds) => {
  if (!seconds) return ''
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  return m > 0 ? `${m}分${s}秒` : `${s}秒`
}
</script>

<style scoped>
:deep(.soft-deleted-row) {
  opacity: 0.45;
  text-decoration: line-through;
}
</style>
