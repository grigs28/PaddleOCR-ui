# 前端 Vue3 实施计划

**日期**: 2026-04-18
**状态**: 待执行
**负责人**: deployment-agent
**关联设计**: [PaddleOCR UI 设计文档](../specs/2026-04-18-paddleocr-ui-design.md)

---

## 概述

本计划覆盖 Vue 3 前端所有页面、组件、composables 和状态管理的完整实现。项目使用 Vite 构建，Element Plus UI 库，Pinia 状态管理，WebSocket 实时通信。

**技术栈**: Vue 3.5 + Vite 6 + Vue Router 4 + Pinia 2 + Axios + Element Plus 2 + @vueuse/core

**项目根目录**: `/opt/webapp/PaddleOCR-ui/frontend/`

**API 基地址**: `/api`（开发环境通过 Vite proxy 转发到 `http://localhost:8080`）

---

## Task 1: 项目入口和路由配置

**目标**: 创建 Vue 应用入口、路由配置和全局样式。

### 1.1 src/main.js

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/main.js`

```javascript
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import zhCn from 'element-plus/dist/locale/zh-cn.mjs'

import App from './App.vue'
import router from './router'
import './style.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(ElementPlus, { locale: zhCn })

app.mount('#app')
```

### 1.2 src/App.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/App.vue`

```vue
<template>
  <router-view />
</template>

<script setup>
</script>
```

### 1.3 src/style.css

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/style.css`

```css
:root {
  --primary-color: #409eff;
  --bg-color: #f5f7fa;
  --header-height: 60px;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

html, body, #app {
  height: 100%;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

body {
  background-color: var(--bg-color);
}

.page-container {
  padding: 20px;
}
```

### 1.4 src/router/index.js

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/router/index.js`

```javascript
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('../views/LoginView.vue'),
    meta: { requiresAuth: false }
  },
  {
    path: '/',
    component: () => import('../components/AppLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'Dashboard',
        component: () => import('../views/DashboardView.vue')
      },
      {
        path: 'tasks/:id',
        name: 'TaskDetail',
        component: () => import('../views/TaskDetailView.vue'),
        props: true
      },
      {
        path: 'admin',
        name: 'Admin',
        component: () => import('../views/AdminView.vue'),
        meta: { requiresAdmin: true }
      },
      {
        path: 'api-docs',
        name: 'ApiDocs',
        component: () => import('../views/ApiDocsView.vue')
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to) => {
  const { useUserStore } = await import('../stores/user')
  const userStore = useUserStore()

  if (to.meta.requiresAuth !== false && !userStore.isLoggedIn) {
    return { name: 'Login' }
  }

  if (to.meta.requiresAdmin && !userStore.isAdmin) {
    return { name: 'Dashboard' }
  }
})

export default router
```

**验证步骤**:
1. `npm run dev` 启动后无报错
2. 访问 `/login` 显示登录页面
3. 未登录访问 `/` 自动跳转到 `/login`
4. 路由切换正常，浏览器后退/前进正常

**Commit**: `feat(frontend): add app entry, router and global styles`

---

## Task 2: 布局组件 AppLayout

**目标**: 创建带导航栏的主布局组件。

### 2.1 src/components/AppLayout.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/components/AppLayout.vue`

```vue
<template>
  <el-container class="app-layout">
    <el-header class="app-header">
      <div class="header-left">
        <h1 class="app-title">PaddleOCR</h1>
      </div>
      <div class="header-right">
        <el-menu mode="horizontal" :ellipsis="false" router :default-active="activeMenu">
          <el-menu-item index="/">任务列表</el-menu-item>
          <el-menu-item index="/admin" v-if="userStore.isAdmin">管理后台</el-menu-item>
          <el-menu-item index="/api-docs">API 文档</el-menu-item>
        </el-menu>
        <el-dropdown @command="handleCommand">
          <span class="user-info">
            {{ userStore.displayName }}
            <el-icon><arrow-down /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </el-header>
    <el-main class="app-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDown } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const activeMenu = computed(() => {
  if (route.path.startsWith('/admin')) return '/admin'
  if (route.path.startsWith('/api-docs')) return '/api-docs'
  return '/'
})

const handleCommand = (command) => {
  if (command === 'logout') {
    userStore.logout()
    router.push('/login')
  }
}
</script>

<style scoped>
.app-layout {
  height: 100%;
}
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 20px;
  height: var(--header-height);
}
.app-title {
  font-size: 20px;
  font-weight: 600;
  color: #303133;
  margin: 0;
}
.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
  color: #606266;
  font-size: 14px;
}
.app-main {
  background: var(--bg-color);
  overflow-y: auto;
}
</style>
```

**验证步骤**:
1. 登录后显示顶部导航栏
2. 用户名正确显示
3. 菜单路由跳转正常
4. 退出登录跳转到登录页
5. 管理员可见"管理后台"菜单

**Commit**: `feat(frontend): add AppLayout with navigation header`

---

## Task 3: Pinia 用户状态管理

### 3.1 src/stores/user.js

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/stores/user.js`

```javascript
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../composables/useApi'

export const useUserStore = defineStore('user', () => {
  const username = ref(localStorage.getItem('username') || '')
  const displayName = ref(localStorage.getItem('displayName') || '')
  const isAdmin = ref(localStorage.getItem('isAdmin') === 'true')
  const token = ref(localStorage.getItem('token') || '')

  const isLoggedIn = computed(() => !!token.value)

  function setUser(data) {
    username.value = data.username
    displayName.value = data.display_name || data.username
    isAdmin.value = data.is_admin === 1
    token.value = data.token

    localStorage.setItem('username', data.username)
    localStorage.setItem('displayName', displayName.value)
    localStorage.setItem('isAdmin', String(isAdmin.value))
    localStorage.setItem('token', data.token)
  }

  function logout() {
    username.value = ''
    displayName.value = ''
    isAdmin.value = false
    token.value = ''

    localStorage.removeItem('username')
    localStorage.removeItem('displayName')
    localStorage.removeItem('isAdmin')
    localStorage.removeItem('token')
  }

  return {
    username,
    displayName,
    isAdmin,
    token,
    isLoggedIn,
    setUser,
    logout
  }
})
```

**验证步骤**:
1. 登录后 store 正确存储用户信息
2. 刷新页面后状态从 localStorage 恢复
3. 登出后 store 和 localStorage 都被清空
4. `isLoggedIn` 计算属性正确响应

**Commit**: `feat(frontend): add Pinia user store`

---

## Task 4: Composables

### 4.1 src/composables/useApi.js

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/composables/useApi.js`

```javascript
import axios from 'axios'
import { useUserStore } from '../stores/user'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000
})

api.interceptors.request.use((config) => {
  const userStore = useUserStore()
  if (userStore.token) {
    config.headers.Authorization = `Bearer ${userStore.token}`
  }
  return config
})

api.interceptors.response.use(
  (response) => response.data,
  (error) => {
    if (error.response?.status === 401) {
      const userStore = useUserStore()
      userStore.logout()
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

export { api }

// 认证 API
export const authApi = {
  verifyTicket: (ticket) => api.get(`/auth/callback`, { params: { ticket } }),
  logout: () => api.post('/auth/logout'),
  getProfile: () => api.get('/auth/profile'),
}

// 任务 API
export const taskApi = {
  list: (params) => api.get('/v1/tasks', { params }),
  get: (id) => api.get(`/v1/tasks/${id}`),
  create: (formData) => api.post('/v1/ocr', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000,
  }),
  delete: (id) => api.delete(`/v1/tasks/${id}`),
  downloadResult: (id, format) => api.get(`/v1/tasks/${id}/result`, {
    params: { format },
    responseType: 'blob',
  }),
  retry: (id) => api.post(`/v1/tasks/${id}/retry`),
}

// 管理 API
export const adminApi = {
  getQueueStatus: () => api.get('/admin/queue'),
  pauseQueue: () => api.post('/admin/queue/pause'),
  resumeQueue: () => api.post('/admin/queue/resume'),
  getConfig: () => api.get('/admin/config'),
  updateConfig: (data) => api.put('/admin/config', data),
  listUsers: () => api.get('/admin/users'),
  listAllTasks: (params) => api.get('/admin/tasks', { params }),
}

// 格式/类型 API
export const systemApi = {
  getFormats: () => api.get('/v1/formats'),
  getTaskTypes: () => api.get('/v1/task-types'),
}
```

### 4.2 src/composables/useAuth.js

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/composables/useAuth.js`

```javascript
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useUserStore } from '../stores/user'
import { authApi } from './useApi'

const YZ_LOGIN_URL = import.meta.env.VITE_YZ_LOGIN_URL || 'http://192.168.0.19:5555'
const APP_BASE_URL = import.meta.env.VITE_APP_BASE_URL || 'http://localhost:8080'

export function useAuth() {
  const router = useRouter()
  const userStore = useUserStore()
  const loading = ref(false)
  const error = ref('')

  function redirectToLogin() {
    const callbackUrl = `${APP_BASE_URL}/auth/callback`
    window.location.href = `${YZ_LOGIN_URL}/login?from=${encodeURIComponent(callbackUrl)}`
  }

  async function handleTicketCallback(ticket) {
    loading.value = true
    error.value = ''
    try {
      const data = await authApi.verifyTicket(ticket)
      userStore.setUser(data)
      router.push('/')
    } catch (err) {
      error.value = err.response?.data?.detail || '登录验证失败'
    } finally {
      loading.value = false
    }
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // 忽略登出请求错误
    }
    userStore.logout()
    router.push('/login')
  }

  return {
    loading,
    error,
    redirectToLogin,
    handleTicketCallback,
    logout
  }
}
```

### 4.3 src/composables/useWebSocket.js

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/composables/useWebSocket.js`

```javascript
import { ref, onMounted, onUnmounted } from 'vue'
import { useUserStore } from '../stores/user'

export function useWebSocket() {
  const userStore = useUserStore()
  const connected = ref(false)
  const listeners = new Map()
  let ws = null
  let reconnectTimer = null
  let reconnectAttempts = 0
  const MAX_RECONNECT = 5
  const BASE_DELAY = 1000

  function getUrl() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const host = window.location.host
    return `${protocol}//${host}/ws/progress?token=${userStore.token}`
  }

  function connect() {
    if (ws?.readyState === WebSocket.OPEN) return

    ws = new WebSocket(getUrl())

    ws.onopen = () => {
      connected.value = true
      reconnectAttempts = 0
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const type = data.type
        const cbs = listeners.get(type)
        if (cbs) {
          cbs.forEach((cb) => cb(data))
        }
      } catch {
        // 忽略解析错误
      }
    }

    ws.onclose = () => {
      connected.value = false
      scheduleReconnect()
    }

    ws.onerror = () => {
      connected.value = false
    }
  }

  function scheduleReconnect() {
    if (reconnectAttempts >= MAX_RECONNECT) return
    const delay = BASE_DELAY * Math.pow(2, reconnectAttempts)
    reconnectAttempts++
    reconnectTimer = setTimeout(connect, delay)
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.onclose = null
      ws.close()
      ws = null
    }
    connected.value = false
  }

  function on(type, callback) {
    if (!listeners.has(type)) {
      listeners.set(type, new Set())
    }
    listeners.get(type).add(callback)
    return () => listeners.get(type)?.delete(callback)
  }

  onMounted(() => {
    if (userStore.isLoggedIn) {
      connect()
    }
  })

  onUnmounted(() => {
    disconnect()
  })

  return { connected, connect, disconnect, on }
}
```

**验证步骤**:
1. API 请求自动附加 Authorization 头
2. 401 响应自动跳转登录页
3. yz-login 跳转和回调流程正确
4. WebSocket 连接、重连和消息分发正常

**Commit**: `feat(frontend): add composables (useApi, useAuth, useWebSocket)`

---

## Task 5: 登录页 LoginView.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/views/LoginView.vue`

```vue
<template>
  <div class="login-page">
    <div class="login-card">
      <h2 class="login-title">PaddleOCR Web UI</h2>
      <p class="login-subtitle">智能文档识别平台</p>

      <div v-if="loading" class="login-loading">
        <el-icon class="is-loading" :size="32"><loading /></el-icon>
        <p>正在验证登录...</p>
      </div>

      <div v-else-if="error" class="login-error">
        <el-alert :title="error" type="error" show-icon :closable="false" />
        <el-button type="primary" @click="retryLogin" style="margin-top: 16px;">
          重新登录
        </el-button>
      </div>

      <div v-else class="login-action">
        <el-button type="primary" size="large" @click="redirectToLogin" :loading="loading">
          登录
        </el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import { useAuth } from '../composables/useAuth'

const route = useRoute()
const { loading, error, redirectToLogin, handleTicketCallback } = useAuth()

function retryLogin() {
  redirectToLogin()
}

onMounted(async () => {
  const ticket = route.query.ticket
  if (ticket) {
    await handleTicketCallback(ticket)
  }
})
</script>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  background: #fff;
  border-radius: 12px;
  padding: 48px 40px;
  width: 400px;
  text-align: center;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}
.login-title {
  font-size: 28px;
  font-weight: 700;
  color: #303133;
  margin-bottom: 8px;
}
.login-subtitle {
  font-size: 14px;
  color: #909399;
  margin-bottom: 32px;
}
.login-loading,
.login-error {
  padding: 20px 0;
}
.login-action {
  padding: 20px 0;
}
.login-action .el-button {
  width: 100%;
}
</style>
```

**验证步骤**:
1. 访问 `/login` 显示登录按钮
2. 点击登录跳转到 yz-login
3. yz-login 回调带 ticket 参数时自动验证
4. 验证失败显示错误信息和重新登录按钮
5. 验证成功跳转到主页

**Commit**: `feat(frontend): add LoginView with yz-login integration`

---

## Task 6: 文件上传组件 FileUploader.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/components/FileUploader.vue`

```vue
<template>
  <el-upload
    ref="uploadRef"
    class="file-uploader"
    drag
    multiple
    :auto-upload="false"
    :limit="10"
    :on-change="handleFileChange"
    :on-remove="handleFileRemove"
    :before-upload="beforeUpload"
    accept=".pdf,.jpg,.jpeg,.png,.bmp,.tiff,.tif,.docx,.xlsx"
  >
    <el-icon class="el-icon--upload"><upload-filled /></el-icon>
    <div class="el-upload__text">
      拖拽文件到此处，或 <em>点击上传</em>
    </div>
    <template #tip>
      <div class="el-upload__tip">
        支持 PDF、图片（JPG/PNG/BMP/TIFF）、Word、Excel 文件，单个文件最大 100MB
      </div>
    </template>
  </el-upload>
</template>

<script setup>
import { ref } from 'vue'
import { UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const MAX_SIZE = 100 * 1024 * 1024 // 100MB

const uploadRef = ref()
const fileList = ref([])

const emit = defineEmits(['update:files'])

function handleFileChange(file) {
  if (file.size > MAX_SIZE) {
    ElMessage.error(`文件 ${file.name} 超过 100MB 限制`)
    uploadRef.value.handleRemove(file)
    return
  }
  fileList.value.push(file)
  emit('update:files', fileList.value)
}

function handleFileRemove(file) {
  const index = fileList.value.findIndex((f) => f.uid === file.uid)
  if (index > -1) {
    fileList.value.splice(index, 1)
  }
  emit('update:files', fileList.value)
}

function beforeUpload(file) {
  const allowedTypes = [
    'application/pdf',
    'image/jpeg', 'image/png', 'image/bmp', 'image/tiff',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
  ]
  if (!allowedTypes.includes(file.type)) {
    ElMessage.error('不支持的文件类型')
    return false
  }
  return true
}

function clearFiles() {
  fileList.value = []
  uploadRef.value?.clearFiles()
  emit('update:files', [])
}

defineExpose({ clearFiles })
</script>

<style scoped>
.file-uploader {
  width: 100%;
}
.file-uploader :deep(.el-upload-dragger) {
  padding: 40px;
}
</style>
```

**验证步骤**:
1. 拖拽文件到上传区域正常
2. 点击上传弹出文件选择对话框
3. 多文件选择正常
4. 超过 100MB 文件被拒绝并提示
5. 不支持的文件类型被拒绝
6. 清除文件功能正常

**Commit**: `feat(frontend): add FileUploader component with drag-and-drop`

---

## Task 7: 输出格式选择器 FormatSelector.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/components/FormatSelector.vue`

```vue
<template>
  <div class="format-selector">
    <label class="selector-label">输出格式：</label>
    <el-checkbox-group v-model="selectedFormats" @change="handleChange">
      <el-checkbox v-for="fmt in formats" :key="fmt.value" :label="fmt.value">
        {{ fmt.label }}
      </el-checkbox>
    </el-checkbox-group>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const formats = [
  { value: 'markdown', label: 'Markdown' },
  { value: 'json', label: 'JSON' },
  { value: 'txt', label: 'TXT' },
  { value: 'docx', label: 'Word (DOCX)' },
]

const selectedFormats = ref(['markdown'])

const emit = defineEmits(['update:formats'])

function handleChange(value) {
  emit('update:formats', value)
}
</script>

<style scoped>
.format-selector {
  display: flex;
  align-items: center;
  gap: 12px;
}
.selector-label {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
}
</style>
```

**验证步骤**:
1. 默认选中 Markdown
2. 多选切换正常
3. emit 事件正确传递选中值

**Commit**: `feat(frontend): add FormatSelector component`

---

## Task 8: 进度条 ProgressBar.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/components/ProgressBar.vue`

```vue
<template>
  <div class="progress-bar" v-if="task">
    <el-progress
      :percentage="task.progress"
      :status="progressStatus"
      :stroke-width="20"
      :text-inside="true"
    />
    <p class="progress-message" v-if="task.status === 'processing'">
      {{ task.progress_message || `正在处理... ${task.progress}%` }}
    </p>
    <p class="progress-message" v-if="task.status === 'queued'">
      排队中，前方等待 {{ queuePosition }} 个任务
    </p>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  task: {
    type: Object,
    default: null
  },
  queuePosition: {
    type: Number,
    default: 0
  }
})

const progressStatus = computed(() => {
  if (!props.task) return ''
  switch (props.task.status) {
    case 'completed': return 'success'
    case 'failed': return 'exception'
    case 'cancelled': return 'warning'
    default: return ''
  }
})
</script>

<style scoped>
.progress-bar {
  padding: 8px 0;
}
.progress-message {
  margin-top: 8px;
  font-size: 13px;
  color: #909399;
}
</style>
```

**验证步骤**:
1. 进度百分比正确显示
2. 完成状态显示绿色
3. 失败状态显示红色
4. 处理中显示进度信息
5. 排队中显示等待数量

**Commit**: `feat(frontend): add ProgressBar component`

---

## Task 9: 任务卡片 TaskCard.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/components/TaskCard.vue`

```vue
<template>
  <el-card class="task-card" :body-style="{ padding: '16px' }">
    <div class="task-header">
      <div class="task-info">
        <el-tag :type="statusTagType" size="small">{{ statusLabel }}</el-tag>
        <span class="task-filename">{{ task.input_filename }}</span>
        <span class="task-type">{{ task.task_type?.toUpperCase() }}</span>
      </div>
      <div class="task-actions">
        <el-button
          v-if="task.status === 'completed'"
          type="primary"
          size="small"
          link
          @click="$emit('view', task)"
        >
          查看结果
        </el-button>
        <el-button
          v-if="task.status === 'failed'"
          size="small"
          link
          @click="$emit('retry', task)"
        >
          重试
        </el-button>
        <el-button
          size="small"
          link
          type="danger"
          @click="handleDelete"
        >
          删除
        </el-button>
      </div>
    </div>

    <ProgressBar
      v-if="['queued', 'processing'].includes(task.status)"
      :task="task"
    />

    <div class="task-meta">
      <span>{{ formatFileSize(task.input_file_size) }}</span>
      <span>{{ formatTime(task.created_at) }}</span>
      <span v-if="task.output_formats">
        输出: {{ task.output_formats }}
      </span>
    </div>

    <div class="task-error" v-if="task.status === 'failed' && task.error_message">
      <el-alert :title="task.error_message" type="error" :closable="false" show-icon />
    </div>
  </el-card>
</template>

<script setup>
import { ElMessageBox, ElMessage } from 'element-plus'
import ProgressBar from './ProgressBar.vue'

const props = defineProps({
  task: { type: Object, required: true }
})

defineEmits(['view', 'retry', 'delete'])

const statusMap = {
  pending: { label: '等待中', type: 'info' },
  queued: { label: '排队中', type: 'warning' },
  processing: { label: '处理中', type: '' },
  completed: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}

const statusLabel = statusMap[props.task.status]?.label || props.task.status
const statusTagType = statusMap[props.task.status]?.type || 'info'

function formatFileSize(bytes) {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024
    i++
  }
  return `${size.toFixed(1)} ${units[i]}`
}

function formatTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}

function handleDelete() {
  ElMessageBox.confirm('确定删除此任务？', '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(() => {
    emit('delete', props.task)
  }).catch(() => {})
}

const emit = defineEmits(['view', 'retry', 'delete'])
</script>

<style scoped>
.task-card {
  margin-bottom: 12px;
}
.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.task-info {
  display: flex;
  align-items: center;
  gap: 8px;
}
.task-filename {
  font-size: 14px;
  font-weight: 500;
  color: #303133;
}
.task-type {
  font-size: 12px;
  color: #909399;
}
.task-actions {
  display: flex;
  gap: 4px;
}
.task-meta {
  display: flex;
  gap: 16px;
  margin-top: 8px;
  font-size: 12px;
  color: #909399;
}
.task-error {
  margin-top: 8px;
}
</style>
```

**验证步骤**:
1. 任务状态标签颜色正确
2. 进度条在处理中/排队中时显示
3. 文件大小和时间格式化正确
4. 删除确认弹窗正常
5. 操作按钮根据状态正确显示/隐藏

**Commit**: `feat(frontend): add TaskCard component`

---

## Task 10: 任务列表 TaskList.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/components/TaskList.vue`

```vue
<template>
  <div class="task-list">
    <div class="list-header">
      <div class="list-filters">
        <el-select v-model="statusFilter" placeholder="状态筛选" clearable size="small" style="width: 120px;">
          <el-option label="全部" value="" />
          <el-option label="等待中" value="pending" />
          <el-option label="排队中" value="queued" />
          <el-option label="处理中" value="processing" />
          <el-option label="已完成" value="completed" />
          <el-option label="失败" value="failed" />
        </el-select>
        <el-select v-model="typeFilter" placeholder="类型筛选" clearable size="small" style="width: 120px;">
          <el-option label="全部" value="" />
          <el-option label="OCR" value="ocr" />
          <el-option label="表格" value="table" />
          <el-option label="公式" value="formula" />
          <el-option label="图表" value="chart" />
        </el-select>
      </div>
      <el-button size="small" @click="refresh" :loading="loading">刷新</el-button>
    </div>

    <div v-loading="loading" class="list-content">
      <el-empty v-if="!loading && tasks.length === 0" description="暂无任务" />
      <TaskCard
        v-for="task in filteredTasks"
        :key="task.id"
        :task="task"
        @view="(t) => $emit('view', t)"
        @retry="(t) => $emit('retry', t)"
        @delete="(t) => $emit('delete', t)"
      />
    </div>

    <el-pagination
      v-if="total > pageSize"
      class="list-pagination"
      layout="prev, pager, next"
      :total="total"
      :page-size="pageSize"
      :current-page="currentPage"
      @current-change="handlePageChange"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { taskApi } from '../composables/useApi'
import TaskCard from './TaskCard.vue'

const props = defineProps({
  autoRefresh: { type: Boolean, default: true }
})

defineEmits(['view', 'retry', 'delete'])

const tasks = ref([])
const loading = ref(false)
const total = ref(0)
const currentPage = ref(1)
const pageSize = 20
const statusFilter = ref('')
const typeFilter = ref('')

let refreshTimer = null

const filteredTasks = computed(() => {
  return tasks.value.filter((t) => {
    if (statusFilter.value && t.status !== statusFilter.value) return false
    if (typeFilter.value && t.task_type !== typeFilter.value) return false
    return true
  })
})

async function fetchTasks() {
  loading.value = true
  try {
    const data = await taskApi.list({
      page: currentPage.value,
      page_size: pageSize,
    })
    tasks.value = data.items || data
    total.value = data.total || tasks.value.length
  } catch (err) {
    console.error('获取任务列表失败:', err)
  } finally {
    loading.value = false
  }
}

function refresh() {
  fetchTasks()
}

function handlePageChange(page) {
  currentPage.value = page
  fetchTasks()
}

onMounted(() => {
  fetchTasks()
  if (props.autoRefresh) {
    refreshTimer = setInterval(fetchTasks, 5000)
  }
})

// 组件卸载时清除定时器
import { onUnmounted } from 'vue'
onUnmounted(() => {
  if (refreshTimer) {
    clearInterval(refreshTimer)
  }
})
</script>

<style scoped>
.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}
.list-filters {
  display: flex;
  gap: 8px;
}
.list-pagination {
  margin-top: 16px;
  display: flex;
  justify-content: center;
}
</style>
```

**验证步骤**:
1. 任务列表正确加载和显示
2. 状态筛选和类型筛选正常
3. 分页正常
4. 自动刷新每 5 秒执行
5. 组件卸载时定时器被清除
6. 空列表显示空状态

**Commit**: `feat(frontend): add TaskList component with filters and pagination`

---

## Task 11: 主面板 DashboardView.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/views/DashboardView.vue`

```vue
<template>
  <div class="dashboard page-container">
    <!-- 上传区域 -->
    <el-card class="upload-card">
      <template #header>
        <span>新建 OCR 任务</span>
      </template>

      <div class="upload-form">
        <FileUploader ref="uploaderRef" @update:files="handleFilesChange" />

        <div class="form-options">
          <div class="option-row">
            <label>任务类型：</label>
            <el-radio-group v-model="taskType">
              <el-radio-button label="ocr">OCR 识别</el-radio-button>
              <el-radio-button label="table">表格识别</el-radio-button>
              <el-radio-button label="formula">公式识别</el-radio-button>
              <el-radio-button label="chart">图表识别</el-radio-button>
            </el-radio-group>
          </div>

          <FormatSelector @update:formats="handleFormatsChange" />
        </div>

        <el-button
          type="primary"
          size="large"
          :loading="submitting"
          :disabled="files.length === 0"
          @click="submitTasks"
          style="margin-top: 16px;"
        >
          提交任务
        </el-button>
      </div>
    </el-card>

    <!-- 任务列表 -->
    <el-card class="tasks-card" style="margin-top: 20px;">
      <template #header>
        <span>任务列表</span>
      </template>
      <TaskList
        @view="viewTask"
        @retry="retryTask"
        @delete="deleteTask"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { taskApi } from '../composables/useApi'
import FileUploader from '../components/FileUploader.vue'
import FormatSelector from '../components/FormatSelector.vue'
import TaskList from '../components/TaskList.vue'

const router = useRouter()
const uploaderRef = ref()
const files = ref([])
const taskType = ref('ocr')
const outputFormats = ref(['markdown'])
const submitting = ref(false)

function handleFilesChange(newFiles) {
  files.value = newFiles
}

function handleFormatsChange(formats) {
  outputFormats.value = formats
}

async function submitTasks() {
  if (files.value.length === 0) {
    ElMessage.warning('请先选择文件')
    return
  }

  submitting.value = true
  let successCount = 0

  try {
    for (const file of files.value) {
      const formData = new FormData()
      formData.append('file', file.raw)
      formData.append('task_type', taskType.value)
      formData.append('output_formats', JSON.stringify(outputFormats.value))

      await taskApi.create(formData)
      successCount++
    }

    ElMessage.success(`已提交 ${successCount} 个任务`)
    uploaderRef.value?.clearFiles()
    files.value = []
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '提交失败')
  } finally {
    submitting.value = false
  }
}

function viewTask(task) {
  router.push(`/tasks/${task.id}`)
}

async function retryTask(task) {
  try {
    await taskApi.retry(task.id)
    ElMessage.success('已重新提交任务')
  } catch (err) {
    ElMessage.error('重试失败')
  }
}

async function deleteTask(task) {
  try {
    await taskApi.delete(task.id)
    ElMessage.success('任务已删除')
  } catch (err) {
    ElMessage.error('删除失败')
  }
}
</script>

<style scoped>
.upload-card {
  max-width: 900px;
  margin: 0 auto;
}
.tasks-card {
  max-width: 900px;
  margin: 0 auto;
}
.form-options {
  margin-top: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.option-row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.option-row label {
  font-size: 14px;
  color: #606266;
  white-space: nowrap;
}
</style>
```

**验证步骤**:
1. 文件上传区域显示正常
2. 任务类型选择正常
3. 输出格式选择正常
4. 提交单个文件任务成功
5. 提交多个文件任务成功
6. 无文件时提交按钮禁用
7. 任务列表显示在下方

**Commit**: `feat(frontend): add DashboardView with upload and task list`

---

## Task 12: 任务详情 TaskDetailView.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/views/TaskDetailView.vue`

```vue
<template>
  <div class="task-detail page-container" v-loading="loading">
    <el-page-header @back="$router.push('/')" title="返回" content="任务详情" />

    <el-card v-if="task" style="margin-top: 16px;">
      <div class="detail-header">
        <div>
          <el-tag :type="statusTagType">{{ statusLabel }}</el-tag>
          <span class="detail-filename">{{ task.input_filename }}</span>
        </div>
        <div class="detail-actions">
          <el-button v-if="task.status === 'failed'" @click="retryTask">重试</el-button>
          <el-button type="danger" @click="deleteTask">删除</el-button>
        </div>
      </div>

      <ProgressBar v-if="['queued', 'processing'].includes(task.status)" :task="task" />

      <el-descriptions :column="2" border style="margin-top: 16px;">
        <el-descriptions-item label="任务类型">{{ task.task_type }}</el-descriptions-item>
        <el-descriptions-item label="文件大小">{{ formatFileSize(task.input_file_size) }}</el-descriptions-item>
        <el-descriptions-item label="输出格式">{{ task.output_formats }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatTime(task.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="开始时间">{{ formatTime(task.started_at) }}</el-descriptions-item>
        <el-descriptions-item label="完成时间">{{ formatTime(task.completed_at) }}</el-descriptions-item>
        <el-descriptions-item label="错误信息" :span="2" v-if="task.error_message">
          <span style="color: #f56c6c;">{{ task.error_message }}</span>
        </el-descriptions-item>
      </el-descriptions>

      <!-- 结果预览和下载 -->
      <div v-if="task.status === 'completed'" class="result-section" style="margin-top: 24px;">
        <h3>识别结果</h3>
        <ResultPreview :task-id="task.id" :formats="parseFormats(task.output_formats)" />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { taskApi } from '../composables/useApi'
import ProgressBar from '../components/ProgressBar.vue'
import ResultPreview from '../components/ResultPreview.vue'

const route = useRoute()
const router = useRouter()
const task = ref(null)
const loading = ref(true)

const statusMap = {
  pending: { label: '等待中', type: 'info' },
  queued: { label: '排队中', type: 'warning' },
  processing: { label: '处理中', type: '' },
  completed: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
}

const statusLabel = computed(() => statusMap[task.value?.status]?.label || '')
const statusTagType = computed(() => statusMap[task.value?.status]?.type || 'info')

function parseFormats(str) {
  try {
    return JSON.parse(str)
  } catch {
    return str ? str.split(',') : []
  }
}

function formatFileSize(bytes) {
  if (!bytes) return '-'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let size = bytes
  while (size >= 1024 && i < units.length - 1) { size /= 1024; i++ }
  return `${size.toFixed(1)} ${units[i]}`
}

function formatTime(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN')
}

async function fetchTask() {
  loading.value = true
  try {
    task.value = await taskApi.get(route.params.id)
  } catch (err) {
    ElMessage.error('获取任务详情失败')
    router.push('/')
  } finally {
    loading.value = false
  }
}

async function retryTask() {
  try {
    await taskApi.retry(task.value.id)
    ElMessage.success('已重新提交')
    fetchTask()
  } catch { ElMessage.error('重试失败') }
}

async function deleteTask() {
  try {
    await ElMessageBox.confirm('确定删除此任务？', '提示', { type: 'warning' })
    await taskApi.delete(task.value.id)
    ElMessage.success('已删除')
    router.push('/')
  } catch { /* 取消 */ }
}

onMounted(fetchTask)
</script>

<style scoped>
.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.detail-filename {
  margin-left: 8px;
  font-size: 16px;
  font-weight: 500;
}
.result-section h3 {
  margin-bottom: 12px;
  font-size: 16px;
}
</style>
```

**验证步骤**:
1. 任务详情正确加载
2. 返回按钮导航到主页
3. 进度条在处理中显示
4. 完成后显示结果预览组件
5. 重试和删除功能正常

**Commit**: `feat(frontend): add TaskDetailView with result preview`

---

## Task 13: 结果预览 ResultPreview.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/components/ResultPreview.vue`

```vue
<template>
  <div class="result-preview">
    <el-tabs v-model="activeFormat">
      <el-tab-pane
        v-for="fmt in formats"
        :key="fmt"
        :label="formatLabel(fmt)"
        :name="fmt"
      >
        <div class="preview-content" v-loading="loading">
          <!-- Markdown 渲染 -->
          <div v-if="fmt === 'markdown' && content" class="markdown-body" v-html="renderedMarkdown" />
          <!-- JSON 渲染 -->
          <pre v-else-if="fmt === 'json'" class="json-content">{{ formattedJson }}</pre>
          <!-- 文本渲染 -->
          <pre v-else class="text-content">{{ content }}</pre>
        </div>
      </el-tab-pane>
    </el-tabs>

    <div class="download-actions">
      <el-button
        v-for="fmt in formats"
        :key="fmt"
        size="small"
        @click="download(fmt)"
      >
        下载 {{ formatLabel(fmt) }}
      </el-button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { taskApi } from '../composables/useApi'

const props = defineProps({
  taskId: { type: [Number, String], required: true },
  formats: { type: Array, default: () => [] }
})

const activeFormat = ref(props.formats[0] || 'markdown')
const content = ref('')
const loading = ref(false)

const formatLabels = {
  markdown: 'Markdown',
  json: 'JSON',
  txt: 'TXT',
  docx: 'Word',
  html: 'HTML',
  xlsx: 'Excel',
}

function formatLabel(fmt) {
  return formatLabels[fmt] || fmt.toUpperCase()
}

const renderedMarkdown = computed(() => {
  // 简单的 Markdown 渲染（实际可引入 marked 库）
  let html = content.value
  return html
})

const formattedJson = computed(() => {
  try {
    return JSON.stringify(JSON.parse(content.value), null, 2)
  } catch {
    return content.value
  }
})

async function fetchContent(format) {
  if (!format) return
  loading.value = true
  try {
    // 对于 markdown/json/txt，直接获取文本内容
    if (['markdown', 'json', 'txt'].includes(format)) {
      const blob = await taskApi.downloadResult(props.taskId, format)
      content.value = await blob.text()
    } else {
      content.value = `请点击下方按钮下载 ${formatLabels[format] || format} 文件`
    }
  } catch (err) {
    content.value = '加载失败'
  } finally {
    loading.value = false
  }
}

async function download(format) {
  try {
    const blob = await taskApi.downloadResult(props.taskId, format)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `result.${format}`
    a.click()
    URL.revokeObjectURL(url)
  } catch {
    console.error('下载失败')
  }
}

watch(activeFormat, fetchContent, { immediate: true })
</script>

<style scoped>
.preview-content {
  min-height: 200px;
  max-height: 600px;
  overflow-y: auto;
  padding: 16px;
  background: #fafafa;
  border-radius: 4px;
  border: 1px solid #ebeef5;
}
.markdown-body {
  font-size: 14px;
  line-height: 1.6;
}
.json-content,
.text-content {
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
.download-actions {
  margin-top: 16px;
  display: flex;
  gap: 8px;
}
</style>
```

**验证步骤**:
1. Tab 切换加载对应格式内容
2. Markdown 内容正确渲染
3. JSON 内容格式化显示
4. 下载按钮触发浏览器下载
5. 非文本格式提示下载

**Commit**: `feat(frontend): add ResultPreview component with multi-format tabs`

---

## Task 14: 管理后台 AdminView.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/views/AdminView.vue`

```vue
<template>
  <div class="admin-view page-container">
    <el-tabs v-model="activeTab">
      <!-- 队列管理 -->
      <el-tab-pane label="队列管理" name="queue">
        <el-card>
          <div class="queue-status">
            <el-descriptions :column="3" border>
              <el-descriptions-item label="队列状态">
                <el-tag :type="queueStatus.paused ? 'danger' : 'success'">
                  {{ queueStatus.paused ? '已暂停' : '运行中' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="等待任务">{{ queueStatus.pending_count || 0 }}</el-descriptions-item>
              <el-descriptions-item label="处理中任务">{{ queueStatus.processing_count || 0 }}</el-descriptions-item>
            </el-descriptions>
            <div style="margin-top: 16px;">
              <el-button
                v-if="queueStatus.paused"
                type="success"
                @click="resumeQueue"
              >
                恢复队列
              </el-button>
              <el-button
                v-else
                type="warning"
                @click="pauseQueue"
              >
                暂停队列
              </el-button>
            </div>
          </div>
        </el-card>
      </el-tab-pane>

      <!-- 系统配置 -->
      <el-tab-pane label="系统配置" name="config">
        <el-card>
          <el-form label-width="140px" style="max-width: 600px;">
            <el-form-item label="最大并发数">
              <el-input-number v-model="config.max_concurrency" :min="1" :max="10" />
            </el-form-item>
            <el-form-item label="最大文件大小(MB)">
              <el-input-number v-model="config.max_file_size_mb" :min="1" :max="500" />
            </el-form-item>
            <el-form-item label="允许的文件类型">
              <el-input v-model="config.allowed_file_types" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="saveConfig">保存配置</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- 所有任务 -->
      <el-tab-pane label="所有任务" name="tasks">
        <TaskList
          :auto-refresh="true"
          @view="(t) => $router.push(`/tasks/${t.id}`)"
          @retry="retryTask"
          @delete="deleteTask"
        />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi, taskApi } from '../composables/useApi'
import TaskList from '../components/TaskList.vue'

const activeTab = ref('queue')
const queueStatus = ref({})
const config = ref({
  max_concurrency: 3,
  max_file_size_mb: 100,
  allowed_file_types: '',
})

async function fetchQueueStatus() {
  try {
    queueStatus.value = await adminApi.getQueueStatus()
  } catch { /* ignore */ }
}

async function fetchConfig() {
  try {
    const data = await adminApi.getConfig()
    config.value = data
  } catch { /* ignore */ }
}

async function pauseQueue() {
  try {
    await adminApi.pauseQueue()
    ElMessage.success('队列已暂停')
    fetchQueueStatus()
  } catch { ElMessage.error('操作失败') }
}

async function resumeQueue() {
  try {
    await adminApi.resumeQueue()
    ElMessage.success('队列已恢复')
    fetchQueueStatus()
  } catch { ElMessage.error('操作失败') }
}

async function saveConfig() {
  try {
    await adminApi.updateConfig(config.value)
    ElMessage.success('配置已保存')
  } catch { ElMessage.error('保存失败') }
}

async function retryTask(task) {
  try {
    await taskApi.retry(task.id)
    ElMessage.success('已重新提交')
  } catch { ElMessage.error('重试失败') }
}

async function deleteTask(task) {
  try {
    await taskApi.delete(task.id)
    ElMessage.success('已删除')
  } catch { ElMessage.error('删除失败') }
}

onMounted(() => {
  fetchQueueStatus()
  fetchConfig()
})
</script>

<style scoped>
.admin-view {
  max-width: 1000px;
  margin: 0 auto;
}
</style>
```

**验证步骤**:
1. 队列状态正确显示
2. 暂停/恢复队列功能正常
3. 系统配置加载和保存正常
4. 所有任务列表显示正确
5. 非管理员无法访问（路由守卫）

**Commit**: `feat(frontend): add AdminView with queue management and config`

---

## Task 15: API 文档页 ApiDocsView.vue

**文件路径**: `/opt/webapp/PaddleOCR-ui/frontend/src/views/ApiDocsView.vue`

```vue
<template>
  <div class="api-docs page-container">
    <el-card>
      <template #header>
        <span>REST API 文档</span>
      </template>

      <div class="docs-content">
        <h3>认证方式</h3>
        <p>所有 API 请求需要在请求头中携带 API Key：</p>
        <pre class="code-block">X-API-Key: ak_xxxxxxxxxxxxxxxx</pre>
        <p>在 Web UI 的管理后台生成 API Key。</p>

        <el-divider />

        <h3>接口列表</h3>

        <div v-for="endpoint in endpoints" :key="endpoint.method + endpoint.path" class="endpoint">
          <div class="endpoint-header">
            <el-tag :type="methodTagType(endpoint.method)" size="small">
              {{ endpoint.method }}
            </el-tag>
            <code class="endpoint-path">{{ endpoint.path }}</code>
            <span class="endpoint-desc">{{ endpoint.description }}</span>
          </div>
          <div v-if="endpoint.body" class="endpoint-body">
            <p>请求体：</p>
            <pre class="code-block">{{ endpoint.body }}</pre>
          </div>
          <div v-if="endpoint.response" class="endpoint-response">
            <p>响应示例：</p>
            <pre class="code-block">{{ endpoint.response }}</pre>
          </div>
        </div>

        <el-divider />

        <h3>SDK 示例</h3>

        <el-tabs>
          <el-tab-pane label="Python">
            <pre class="code-block">import requests

API_KEY = "ak_xxxxxxxxxxxxxxxx"
BASE_URL = "http://localhost:8080/api"

# 提交 OCR 任务
with open("document.pdf", "rb") as f:
    response = requests.post(
        f"{BASE_URL}/v1/ocr",
        headers={"X-API-Key": API_KEY},
        files={"file": f},
        data={
            "task_type": "ocr",
            "output_formats": '["markdown", "json"]'
        }
    )
task = response.json()
task_id = task["task_id"]

# 查询任务状态
response = requests.get(
    f"{BASE_URL}/v1/tasks/{task_id}",
    headers={"X-API-Key": API_KEY}
)
print(response.json())

# 下载结果
response = requests.get(
    f"{BASE_URL}/v1/tasks/{task_id}/result",
    params={"format": "markdown"},
    headers={"X-API-Key": API_KEY}
)
with open("result.md", "w") as f:
    f.write(response.text)</pre>
          </el-tab-pane>
          <el-tab-pane label="cURL">
            <pre class="code-block"># 提交 OCR 任务
curl -X POST http://localhost:8080/api/v1/ocr \
  -H "X-API-Key: ak_xxxxxxxxxxxxxxxx" \
  -F "file=@document.pdf" \
  -F "task_type=ocr" \
  -F 'output_formats=["markdown","json"]'

# 查询任务状态
curl http://localhost:8080/api/v1/tasks/12345 \
  -H "X-API-Key: ak_xxxxxxxxxxxxxxxx"

# 下载结果
curl http://localhost:8080/api/v1/tasks/12345/result?format=markdown \
  -H "X-API-Key: ak_xxxxxxxxxxxxxxxx" \
  -o result.md</pre>
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-card>
  </div>
</template>

<script setup>
const endpoints = [
  {
    method: 'POST',
    path: '/api/v1/ocr',
    description: '提交 OCR 任务',
    body: `multipart/form-data:
  file: 文件（必填）
  task_type: ocr | table | formula | chart
  output_formats: ["markdown", "json", "txt", "docx"]`,
    response: `{
  "task_id": "12345",
  "status": "queued",
  "task_type": "ocr",
  "output_formats": ["markdown", "json"],
  "created_at": "2026-04-18T10:00:00Z",
  "poll_url": "/api/v1/tasks/12345"
}`
  },
  {
    method: 'GET',
    path: '/api/v1/tasks',
    description: '列出当前用户的任务',
    response: `{
  "items": [...],
  "total": 42,
  "page": 1,
  "page_size": 20
}`
  },
  {
    method: 'GET',
    path: '/api/v1/tasks/{id}',
    description: '查询任务状态和详情',
  },
  {
    method: 'GET',
    path: '/api/v1/tasks/{id}/result',
    description: '下载结果文件（query: format=markdown|json|txt|docx）',
  },
  {
    method: 'DELETE',
    path: '/api/v1/tasks/{id}',
    description: '删除任务',
  },
  {
    method: 'GET',
    path: '/api/v1/formats',
    description: '查询支持的输出格式',
  },
  {
    method: 'GET',
    path: '/api/v1/task-types',
    description: '查询支持的任务类型',
  },
]

function methodTagType(method) {
  const map = { GET: 'success', POST: 'warning', PUT: '', DELETE: 'danger' }
  return map[method] || 'info'
}
</script>

<style scoped>
.api-docs {
  max-width: 900px;
  margin: 0 auto;
}
.docs-content h3 {
  margin: 16px 0 8px;
}
.code-block {
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 12px 16px;
  font-family: 'Menlo', 'Monaco', 'Courier New', monospace;
  font-size: 13px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.endpoint {
  margin-bottom: 20px;
  padding: 12px;
  background: #fafafa;
  border-radius: 4px;
  border: 1px solid #ebeef5;
}
.endpoint-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.endpoint-path {
  font-family: monospace;
  font-size: 14px;
  color: #303133;
}
.endpoint-desc {
  color: #909399;
  font-size: 13px;
}
.endpoint-body,
.endpoint-response {
  margin-top: 8px;
}
.endpoint-body p,
.endpoint-response p {
  font-size: 13px;
  color: #606266;
  margin-bottom: 4px;
}
</style>
```

**验证步骤**:
1. 页面渲染正常
2. 所有 API 端点描述完整
3. Python 和 cURL 示例代码正确
4. 代码块样式可读

**Commit**: `feat(frontend): add ApiDocsView with endpoint docs and SDK examples`

---

## 执行顺序和依赖关系

```
Task 1 (入口+路由) ── 基础，最先完成
  ↓
Task 2 (AppLayout) ─── 依赖路由
Task 3 (Pinia store) ── 无依赖，可与 Task 1 并行
Task 4 (Composables) ── 依赖 Task 3
  ↓
Task 5 (LoginView) ─── 依赖 Task 4
Task 6 (FileUploader) ─── 独立组件
Task 7 (FormatSelector) ─── 独立组件
Task 8 (ProgressBar) ─── 独立组件
  ↓
Task 9 (TaskCard) ─── 依赖 Task 8
Task 10 (TaskList) ─── 依赖 Task 9
  ↓
Task 11 (DashboardView) ─── 依赖 Task 6, 7, 10
Task 12 (TaskDetailView) ─── 依赖 Task 8, 13
Task 13 (ResultPreview) ─── 独立组件
Task 14 (AdminView) ─── 依赖 Task 10
Task 15 (ApiDocsView) ─── 独立页面
```

**推荐并行分组**:
- **第一批**: Task 1, Task 3
- **第二批**: Task 2, Task 4, Task 6, Task 7, Task 8, Task 13, Task 15
- **第三批**: Task 5, Task 9
- **第四批**: Task 10, Task 14
- **第五批**: Task 11, Task 12

## 总计文件清单

| # | 文件路径 | 说明 |
|---|---------|------|
| 1.1 | `src/main.js` | 应用入口 |
| 1.2 | `src/App.vue` | 根组件 |
| 1.3 | `src/style.css` | 全局样式 |
| 1.4 | `src/router/index.js` | 路由配置 |
| 2.1 | `src/components/AppLayout.vue` | 布局组件 |
| 3.1 | `src/stores/user.js` | 用户状态 |
| 4.1 | `src/composables/useApi.js` | API 封装 |
| 4.2 | `src/composables/useAuth.js` | 认证逻辑 |
| 4.3 | `src/composables/useWebSocket.js` | WebSocket |
| 5.1 | `src/views/LoginView.vue` | 登录页 |
| 6.1 | `src/components/FileUploader.vue` | 文件上传 |
| 7.1 | `src/components/FormatSelector.vue` | 格式选择 |
| 8.1 | `src/components/ProgressBar.vue` | 进度条 |
| 9.1 | `src/components/TaskCard.vue` | 任务卡片 |
| 10.1 | `src/components/TaskList.vue` | 任务列表 |
| 11.1 | `src/views/DashboardView.vue` | 主面板 |
| 12.1 | `src/views/TaskDetailView.vue` | 任务详情 |
| 13.1 | `src/components/ResultPreview.vue` | 结果预览 |
| 14.1 | `src/views/AdminView.vue` | 管理后台 |
| 15.1 | `src/views/ApiDocsView.vue` | API 文档 |

共 20 个文件，15 个 commit。
