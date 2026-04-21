import { ref, onMounted, onUnmounted } from 'vue'
import { useTaskStore } from '../stores/task'

export function useWebSocket() {
  const connected = ref(false)
  let ws = null
  let reconnectTimer = null
  let pollTimer = null

  const connect = () => {
    const sessionId = document.cookie
      .split('; ')
      .find(row => row.startsWith('paddleocr_session='))
      ?.split('=')[1]
    if (!sessionId) {
      // 无 session，走轮询
      startPolling()
      return
    }

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    try {
      ws = new WebSocket(`${protocol}//${location.host}/ws/progress?session_id=${sessionId}`)
    } catch {
      startPolling()
      return
    }

    ws.onopen = () => {
      connected.value = true
      stopPolling()
    }
    ws.onclose = () => {
      connected.value = false
      // WebSocket 断了，用轮询兜底
      startPolling()
      reconnectTimer = setTimeout(connect, 5000)
    }
    ws.onerror = () => {
      ws.close()
    }
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const taskStore = useTaskStore()
        taskStore.updateTaskProgress(data.task_id, data)
      } catch {}
    }
  }

  // 轮询兜底：有活跃任务时每 3 秒拉一次
  const startPolling = () => {
    if (pollTimer) return
    pollTimer = setInterval(async () => {
      const taskStore = useTaskStore()
      const hasActive = taskStore.sortedTasks.some(
        t => t.status === 'queued' || t.status === 'processing' || t.status === 'pending'
      )
      if (hasActive) {
        await taskStore.fetchActive()
      }
    }, 3000)
  }

  const stopPolling = () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  const disconnect = () => {
    if (reconnectTimer) clearTimeout(reconnectTimer)
    stopPolling()
    if (ws) ws.close()
  }

  onMounted(connect)
  onUnmounted(disconnect)

  return { connected, disconnect }
}
