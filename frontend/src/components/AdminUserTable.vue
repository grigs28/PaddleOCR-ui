<template>
  <el-table :data="users" stripe v-loading="loading">
    <el-table-column prop="id" label="ID" width="80" />
    <el-table-column prop="username" label="用户名" />
    <el-table-column prop="display_name" label="显示名" />
    <el-table-column label="管理员" width="100">
      <template #default="{ row }">
        <el-switch v-model="row.is_admin" :active-value="1" :inactive-value="0"
          @change="(v) => toggleAdmin(row, v)" />
      </template>
    </el-table-column>
    <el-table-column label="创建时间">
      <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
    </el-table-column>
  </el-table>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { formatTime } from '../utils/format'

const users = ref([])
const loading = ref(false)

const fetchUsers = async () => {
  loading.value = true
  try {
    const { data } = await axios.get('/api/v1/admin/users')
    users.value = data.users || []
  } finally {
    loading.value = false
  }
}

const toggleAdmin = async (user, val) => {
  await axios.put(`/api/v1/admin/users/${user.id}`, { is_admin: val })
  ElMessage.success(val ? '已设为管理员' : '已取消管理员')
}

onMounted(fetchUsers)
</script>
