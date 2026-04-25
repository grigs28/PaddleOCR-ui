<template>
  <div>
    <el-upload
      ref="uploadRef"
      drag
      multiple
      :auto-upload="false"
      :show-file-list="false"
      :on-change="handleFiles"
      accept=".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.webp,.doc,.docx,.odt,.rtf,.xls,.xlsx,.ods,.csv,.ppt,.pptx,.odp,.txt,.html,.htm,.dwg,.dxf"
    >
      <el-icon style="font-size: 40px; color: #c0c4cc;"><UploadFilled /></el-icon>
      <div>拖拽文件到此处，或 <em>点击上传</em></div>
      <template #tip>
        <div style="color: #909399; font-size: 12px; margin-top: 4px;">
          支持 PDF、图片、Office 文档、CAD 等 24 种格式，单文件最大 1GB，支持多文件
        </div>
      </template>
    </el-upload>
    <!-- 输出格式选择 -->
    <div style="margin-top: 8px; display: flex; align-items: center; gap: 8px;">
      <span style="font-size: 12px; color: #909399;">输出格式：</span>
      <el-checkbox-group v-model="uploadStore.outputFormats" size="small">
        <el-checkbox v-for="fmt in uploadStore.availableFormats" :key="fmt.value"
          :label="fmt.value">{{ fmt.label }}</el-checkbox>
      </el-checkbox-group>
    </div>
    <!-- 待上传文件列表 -->
    <div v-if="uploadStore.files.length" style="margin-top: 12px;">
      <div v-for="f in uploadStore.files" :key="f.id"
        style="display: flex; align-items: center; justify-content: space-between; padding: 4px 0; font-size: 13px;">
        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%;">
          {{ f.name }} ({{ formatSize(f.size) }})
        </span>
        <div style="display: flex; align-items: center; gap: 8px;">
          <el-tag v-if="f.status === 'uploading'" type="warning" size="small">上传中</el-tag>
          <el-tag v-else-if="f.status === 'done'" type="success" size="small">已提交</el-tag>
          <el-tag v-else-if="f.status === 'error'" type="danger" size="small">{{ f.errorMsg }}</el-tag>
          <el-button v-if="f.status === 'pending' || f.status === 'error'" text type="danger" size="small"
            @click="uploadStore.removeFile(f.id)">移除</el-button>
        </div>
      </div>
      <div style="margin-top: 8px; display: flex; gap: 8px;">
        <el-button type="primary" size="small" @click="uploadStore.startUpload()"
          :loading="uploadStore.uploading" :disabled="uploadStore.pendingFiles.length === 0 || uploadStore.outputFormats.length === 0">
          开始转换 ({{ uploadStore.pendingFiles.length }})
        </el-button>
        <el-button size="small" @click="uploadStore.clearCompleted()">清除已完成</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { UploadFilled } from '@element-plus/icons-vue'
import { useUploadStore } from '../stores/upload'
import { formatSize } from '../utils/format'

const uploadStore = useUploadStore()

const handleFiles = (uploadFile) => {
  uploadStore.addFiles([uploadFile.raw])
}
</script>
