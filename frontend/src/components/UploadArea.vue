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
      <el-checkbox-group :model-value="uploadStore.outputFormats" size="small">
        <el-checkbox v-for="fmt in uploadStore.availableFormats" :key="fmt.value"
          :label="fmt.value"
          :model-value="uploadStore.outputFormats.includes(fmt.value)"
          :disabled="fmt.value !== 'dwg' && uploadStore.outputFormats.includes('dwg')"
          @change="uploadStore.toggleFormat(fmt.value)">{{ fmt.label }}</el-checkbox>
      </el-checkbox-group>
      <span v-if="uploadStore.hasCadFiles && uploadStore.outputFormats.length === 0"
        style="font-size: 12px; color: #909399;">DWG 默认仅转换为 PDF</span>
      <span v-if="uploadStore.hasCadFiles && uploadStore.outputFormats.length > 0 && !uploadStore.outputFormats.includes('dwg')"
        style="font-size: 12px; color: #e6a23c;">将对转换后的 PDF 进行 OCR 文字识别</span>
      <span v-if="!uploadStore.hasCadFiles && uploadStore.outputFormats.includes('dwg') && !uploadStore.hasPdfFiles"
        style="font-size: 12px; color: #e6a23c;">DWG 仅对 PDF 文件生效，且与其他格式互斥</span>
      <!-- DWG PDF 模式选择：单页/合并 互斥 -->
      <template v-if="uploadStore.hasCadFiles">
        <el-checkbox v-model="uploadStore.singlePagePdf" size="small"
          :disabled="uploadStore.outputFormats.includes('dwg')"
          @change="uploadStore.singlePagePdf && (uploadStore.mergePdf = false)"
          style="margin-left: 12px;">单页 PDF</el-checkbox>
        <el-checkbox v-model="uploadStore.mergePdf" size="small"
          :disabled="uploadStore.outputFormats.includes('dwg')"
          @change="uploadStore.mergePdf && (uploadStore.singlePagePdf = false)">合并 PDF</el-checkbox>
      </template>
      <!-- 高精度模式（右对齐）：CAD 图纸 / 密集小字表格 提升分辨率 -->
      <el-tooltip
        content="适用于 AutoCAD 图纸、密集小字表格等场景，VLM 输入分辨率提升至 ~10MP，识别更清晰但耗时增加约 50%。普通文档无需开启。"
        placement="top">
        <div style="margin-left: auto; display: flex; align-items: center; gap: 6px;">
          <span style="font-size: 12px; color: #909399;">高精度</span>
          <el-switch v-model="uploadStore.highPrecision" size="small" />
        </div>
      </el-tooltip>
      <!-- 引擎选择（最右） -->
      <div style="display: flex; align-items: center; gap: 6px;">
        <span style="font-size: 12px; color: #909399;">引擎</span>
        <el-select v-model="uploadStore.engine" size="small" style="width: 150px;">
          <el-option label="PaddleOCR-VL 1.6" value="vl16" />
          <el-option label="PP-OCRv6" value="ppocrv6" />
          <el-option label="MinerU" value="mineru" />
        </el-select>
      </div>
    </div>
    <div v-if="uploadStore.hasMixedCadPdf" style="margin-top: 4px; color: #f56c6c; font-size: 12px;">
      不能同时上传 DWG 和 PDF 文件
    </div>
    <!-- 操作按钮（文件列表上方） -->
    <div v-if="uploadStore.files.length" style="margin-top: 10px; display: flex; gap: 8px; align-items: center;">
      <el-button type="primary" size="small" @click="uploadStore.startUpload()"
        :loading="uploadStore.uploading"
        :disabled="uploadStore.pendingFiles.length === 0 || (!uploadStore.hasCadFiles && uploadStore.outputFormats.length === 0) || uploadStore.hasMixedCadPdf">
        开始转换 ({{ uploadStore.pendingFiles.length }})
      </el-button>
      <el-button size="small" @click="uploadStore.clearCompleted()">清除已完成</el-button>
      <span style="font-size: 12px; color: #909399; margin-left: auto;">共 {{ uploadStore.files.length }} 个文件</span>
    </div>
    <!-- 文件列表（可滚动） -->
    <div v-if="uploadStore.files.length" style="margin-top: 8px; max-height: 200px; overflow-y: auto;">
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
