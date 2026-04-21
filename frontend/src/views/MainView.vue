<template>
  <el-container style="height: 100vh;">
    <el-header style="background: #fff; border-bottom: 1px solid #e4e7ed; display: flex; align-items: center; justify-content: space-between; padding: 0 20px;">
      <div style="display: flex; align-items: center; gap: 16px;">
        <h2 style="margin: 0; font-size: 18px; color: #303133;">PaddleOCR</h2>
        <el-tabs v-model="activeTab" style="margin-bottom: -1px;">
          <el-tab-pane label="上传任务" name="workspace" />
          <el-tab-pane label="文件管理" name="files" />
          <el-tab-pane v-if="userStore.isAdmin" label="管理后台" name="admin" />
        </el-tabs>
      </div>
      <div style="display: flex; align-items: center; gap: 12px;">
        <span style="color: #606266;">{{ userStore.displayName }}</span>
        <el-button text @click="handleLogout">退出</el-button>
      </div>
    </el-header>
    <el-main style="padding: 0; background: #f5f7fa;">
      <TaskWorkspace v-if="activeTab === 'workspace'" />
      <FileManagement v-if="activeTab === 'files'" />
      <AdminPanel v-if="activeTab === 'admin'" />
    </el-main>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { useUserStore } from '../stores/user'
import TaskWorkspace from './TaskWorkspace.vue'
import FileManagement from './FileManagement.vue'
import AdminPanel from './AdminPanel.vue'

const userStore = useUserStore()
const router = useRouter()
const activeTab = ref('workspace')

onMounted(() => { userStore.fetchUser() })

const handleLogout = async () => {
  await axios.post('/auth/logout')
  router.push('/login')
}
</script>
