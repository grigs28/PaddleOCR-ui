<template>
  <el-container style="height: 100vh;">
    <el-header style="background: #fff; border-bottom: 1px solid #e4e7ed; display: flex; align-items: center; justify-content: space-between; padding: 0 20px;">
      <div style="display: flex; align-items: center; gap: 16px;">
        <h2 style="margin: 0; font-size: 18px; color: #303133;">PaddleOCR</h2>
        <span v-if="versionInfo" class="version-link" @click="showChangelog">
          v{{ versionInfo.ui_version }}<template v-if="versionInfo.engine_version !== '未知'"> · {{ versionInfo.engine_version }}</template>
        </span>
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

    <!-- 更新日志弹窗 -->
    <el-dialog v-model="changelogVisible" title="更新日志" width="720px" top="8vh">
      <div v-if="changelogHtml" v-html="changelogHtml" class="markdown-body changelog-body"></div>
      <div v-else style="color: #909399; text-align: center; padding: 40px;">加载中...</div>
    </el-dialog>
  </el-container>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import MarkdownIt from 'markdown-it'
import { useUserStore } from '../stores/user'
import TaskWorkspace from './TaskWorkspace.vue'
import FileManagement from './FileManagement.vue'
import AdminPanel from './AdminPanel.vue'

const userStore = useUserStore()
const router = useRouter()
const activeTab = ref('workspace')
const versionInfo = ref(null)
const changelogVisible = ref(false)
const changelogHtml = ref('')
const md = new MarkdownIt({ html: true, linkify: true })

onMounted(() => {
  userStore.fetchUser()
  axios.get('/api/version').then(({ data }) => { versionInfo.value = data }).catch(() => {})
})

const showChangelog = async () => {
  changelogVisible.value = true
  if (!changelogHtml.value) {
    try {
      const { data } = await axios.get('/api/changelog')
      changelogHtml.value = md.render(data.content || '')
    } catch {
      changelogHtml.value = '<p style="color:#f56c6c">加载失败</p>'
    }
  }
}

const handleLogout = async () => {
  try {
    const { data } = await axios.post('/auth/logout')
    document.cookie = 'paddleocr_session=; path=/; max-age=0'
    // 跳 SSO logout 清掉 SSO session
    window.location.href = data.sso_logout || '/auth/login'
  } catch {
    document.cookie = 'paddleocr_session=; path=/; max-age=0'
    window.location.href = '/auth/login'
  }
}
</script>

<style scoped>
.version-link {
  font-size: 12px;
  color: #909399;
  white-space: nowrap;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: all 0.2s;
}
.version-link:hover {
  color: #409eff;
  background: #ecf5ff;
}
.changelog-body {
  max-height: 65vh;
  overflow-y: auto;
  padding-right: 8px;
  font-size: 14px;
  line-height: 1.7;
}
.changelog-body :deep(h1) { font-size: 20px; margin: 0 0 12px; }
.changelog-body :deep(h2) { font-size: 17px; margin: 20px 0 8px; border-bottom: 1px solid #e4e7ed; padding-bottom: 6px; }
.changelog-body :deep(h3) { font-size: 15px; margin: 14px 0 6px; }
.changelog-body :deep(ul) { padding-left: 20px; margin: 6px 0; }
.changelog-body :deep(a) { color: #409eff; }
</style>
