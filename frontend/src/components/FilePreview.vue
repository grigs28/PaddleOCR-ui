<template>
  <div style="height: 100%; display: flex; align-items: center; justify-content: center;">
    <div v-if="!preview" style="color: #c0c4cc; text-align: center;">
      <el-icon style="font-size: 48px;"><Document /></el-icon>
      <div style="margin-top: 8px;">选择任务查看原文件</div>
    </div>
    <img v-else-if="preview.type === 'image'" :src="preview.url"
      style="max-width: 100%; max-height: 100%; object-fit: contain;" />
    <iframe v-else-if="preview.type === 'pdf'" :src="preview.url"
      style="width: 100%; height: 100%; border: none;" />
    <div v-else style="color: #909399;">无法预览此文件类型</div>
  </div>
</template>

<script setup>
import { Document } from '@element-plus/icons-vue'
defineProps({ preview: Object, taskId: Number })
</script>
