<template>
  <div style="display: flex; height: calc(100vh - 60px);">
    <!-- 左列 -->
    <div style="flex: 1; display: flex; flex-direction: column; border-right: 1px solid #e4e7ed;">
      <div style="padding: 16px; border-bottom: 1px solid #e4e7ed;">
        <UploadArea />
      </div>
      <div style="flex: 1; overflow: auto; padding: 16px;">
        <FilePreview :preview="taskStore.selectedPreview" :task-id="taskStore.selectedTaskId" />
      </div>
    </div>
    <!-- 右列 -->
    <div style="flex: 1; display: flex; flex-direction: column;">
      <div style="padding: 16px; border-bottom: 1px solid #e4e7ed; max-height: 40%; overflow: auto;">
        <TaskQueue />
      </div>
      <div style="flex: 1; overflow: auto; padding: 16px;">
        <MarkdownPreview :result="taskStore.selectedResult" :task-id="taskStore.selectedTaskId" />
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useTaskStore } from '../stores/task'
import { useWebSocket } from '../composables/useWebSocket'
import UploadArea from '../components/UploadArea.vue'
import FilePreview from '../components/FilePreview.vue'
import TaskQueue from '../components/TaskQueue.vue'
import MarkdownPreview from '../components/MarkdownPreview.vue'

const taskStore = useTaskStore()
const { disconnect } = useWebSocket()

onMounted(() => { taskStore.restoreFromApi() })
</script>
