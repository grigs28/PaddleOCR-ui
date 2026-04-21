<template>
  <el-tabs v-model="activeTab" style="padding: 20px;">
    <el-tab-pane label="用户管理" name="users">
      <AdminUserTable />
    </el-tab-pane>
    <el-tab-pane label="API Key 管理" name="apikeys">
      <el-card>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
          <h3 style="margin: 0;">API Keys</h3>
          <div style="display: flex; gap: 8px;">
            <el-input v-model="newKeyName" placeholder="Key 名称" style="width: 150px;" size="small" />
            <el-button type="primary" size="small" @click="createKey">创建</el-button>
          </div>
        </div>
        <el-table :data="apiKeys" stripe>
          <el-table-column prop="name" label="名称" width="150" />
          <el-table-column prop="api_key_prefix" label="Key">
            <template #default="{ row }">
              <span v-if="row._fullKey">{{ row._fullKey }}</span>
              <span v-else>{{ row.api_key_prefix }}</span>
              <el-button v-if="row.is_active" text type="primary" size="small" @click="revealKey(row)">
                <el-icon><View /></el-icon>
              </el-button>
              <el-button v-if="row._fullKey" text type="primary" size="small" @click="copyText(row._fullKey)">
                复制
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }">
              <el-tag :type="row.is_active ? 'success' : 'info'" size="small">
                {{ row.is_active ? '有效' : '已吊销' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="最后使用">
            <template #default="{ row }">{{ row.last_used_at ? formatTime(row.last_used_at) : '-' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="80">
            <template #default="{ row }">
              <el-popconfirm v-if="row.is_active" title="确认吊销此 Key？" @confirm="revokeKey(row.id)">
                <template #reference>
                  <el-button text type="danger" size="small">吊销</el-button>
                </template>
              </el-popconfirm>
              <span v-else style="color: #c0c4cc;">-</span>
            </template>
          </el-table-column>
        </el-table>
      </el-card>

      <!-- 创建成功弹窗 -->
      <el-dialog v-model="showNewKey" title="API Key 已创建" width="520px" :close-on-click-modal="false">
        <el-alert type="warning" :closable="false" style="margin-bottom: 16px;">
          请立即复制保存，此 Key 仅显示一次，关闭后无法再查看完整内容。
        </el-alert>
        <el-input :model-value="newKeyValue" readonly>
          <template #append>
            <el-button @click="copyKey">复制</el-button>
          </template>
        </el-input>
        <template #footer>
          <el-button type="primary" @click="showNewKey = false">我已保存</el-button>
        </template>
      </el-dialog>
    </el-tab-pane>

    <!-- 系统设置 -->
    <el-tab-pane label="系统设置" name="settings">
      <el-card>
        <h3 style="margin: 0 0 16px;">超时与并发配置</h3>
        <el-form label-width="200px" size="small">
          <el-form-item v-for="(meta, key) in settingsData" :key="key" :label="meta.label">
            <el-input-number v-model="settingsData[key].value" :min="meta.min" :max="meta.max" :step="1" />
            <span style="margin-left: 8px; color: #909399; font-size: 12px;">范围: {{ meta.min }} ~ {{ meta.max }}</span>
          </el-form-item>
        </el-form>
        <el-button type="primary" @click="saveSettings" :loading="savingSettings">保存配置</el-button>
      </el-card>
    </el-tab-pane>

    <!-- 系统日志 -->
    <el-tab-pane label="系统日志" name="logs">
      <el-card>
        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
          <h3 style="margin: 0;">系统日志</h3>
          <div style="display: flex; gap: 8px; align-items: center;">
            <span style="font-size: 12px; color: #909399;">显示行数:</span>
            <el-input-number v-model="logLines" :min="50" :max="2000" :step="50" size="small" style="width: 120px;" />
            <el-checkbox v-model="logAutoRefresh" size="small">自动刷新</el-checkbox>
            <el-button size="small" @click="fetchLogs">刷新</el-button>
          </div>
        </div>
        <div style="background: #1e1e1e; color: #d4d4d4; padding: 12px; border-radius: 4px;
          font-family: 'Consolas', 'Monaco', monospace; font-size: 12px; line-height: 1.6;
          max-height: 500px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;">
          <div v-for="(line, i) in logData" :key="i" :style="{ color: logColor(line) }">{{ line }}</div>
          <div v-if="logData.length === 0" style="color: #666;">暂无日志</div>
        </div>
      </el-card>
    </el-tab-pane>
  </el-tabs>
</template>

<script setup>
import { ref, onMounted, watch, onUnmounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import AdminUserTable from '../components/AdminUserTable.vue'
import { formatTime } from '../utils/format'
import { View } from '@element-plus/icons-vue'

const activeTab = ref('users')
const apiKeys = ref([])
const newKeyName = ref('')
const showNewKey = ref(false)
const newKeyValue = ref('')

// --- 系统设置 ---
const settingsData = ref({})
const savingSettings = ref(false)

const fetchSettings = async () => {
  const { data } = await axios.get('/api/v1/admin/settings')
  settingsData.value = data.settings || {}
}

const saveSettings = async () => {
  savingSettings.value = true
  try {
    const body = {}
    for (const [key, meta] of Object.entries(settingsData.value)) {
      body[key] = meta.value
    }
    await axios.put('/api/v1/admin/settings', body)
    ElMessage.success('配置已保存并立即生效')
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingSettings.value = false
  }
}

// --- 系统日志 ---
const logData = ref([])
const logLines = ref(200)
const logAutoRefresh = ref(true)
let logTimer = null

const fetchLogs = async () => {
  try {
    const { data } = await axios.get('/api/v1/admin/logs', { params: { lines: logLines.value } })
    logData.value = data.logs || []
  } catch {}
}

const logColor = (line) => {
  if (line.includes(' ERROR ')) return '#f56c6c'
  if (line.includes(' WARNING ')) return '#e6a23c'
  if (line.includes(' INFO ')) return '#67c23a'
  return '#d4d4d4'
}

watch(logAutoRefresh, (v) => {
  if (v) {
    fetchLogs()
    logTimer = setInterval(fetchLogs, 5000)
  } else {
    clearInterval(logTimer)
    logTimer = null
  }
})

watch(activeTab, (v) => {
  if (v === 'settings') fetchSettings()
  if (v === 'logs') { fetchLogs(); if (logAutoRefresh.value) logTimer = setInterval(fetchLogs, 5000) }
  else { clearInterval(logTimer); logTimer = null }
})

onUnmounted(() => { clearInterval(logTimer) })

// --- API Keys ---
const fetchKeys = async () => {
  const { data } = await axios.get('/auth/api-keys')
  apiKeys.value = data.api_keys || []
}

const createKey = async () => {
  const { data } = await axios.post('/auth/api-keys', null, { params: { name: newKeyName.value || '默认' } })
  newKeyValue.value = data.api_key
  showNewKey.value = true
  newKeyName.value = ''
  fetchKeys()
}

const copyKey = () => {
  const ta = document.createElement('textarea')
  ta.value = newKeyValue.value
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
  ElMessage.success('已复制到剪贴板')
}

const revokeKey = async (id) => {
  await axios.delete(`/auth/api-keys/${id}`)
  ElMessage.success('已吊销')
  fetchKeys()
}

const revealKey = async (row) => {
  const { data } = await axios.get(`/auth/api-keys/${row.id}/reveal`)
  row._fullKey = data.api_key
}

const copyText = (text) => {
  const ta = document.createElement('textarea')
  ta.value = text
  ta.style.position = 'fixed'
  ta.style.opacity = '0'
  document.body.appendChild(ta)
  ta.select()
  document.execCommand('copy')
  document.body.removeChild(ta)
  ElMessage.success('已复制')
}

onMounted(fetchKeys)
</script>
