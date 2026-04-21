<template>
  <div style="height: 100vh; display: flex; align-items: center; justify-content: center; background: var(--bg-color);">
    <el-card style="width: 400px; text-align: center;">
      <template #header>
        <h2 style="margin: 0;">PaddleOCR Web UI</h2>
      </template>
      <p style="color: #909399; margin-bottom: 24px;">正在跳转到统一登录平台...</p>
      <el-icon class="is-loading" :size="32" color="#409eff"><Loading /></el-icon>
    </el-card>
  </div>
</template>

<script setup>
import { Loading } from '@element-plus/icons-vue'

// 自动跳转到 OOS 统一登录
window.location.href = '/auth/login'
</script>
