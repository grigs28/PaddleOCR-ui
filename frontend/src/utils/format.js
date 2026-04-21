export function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

export function statusText(s) {
  return { pending: '等待中', queued: '排队中', processing: '处理中', completed: '已完成', failed: '失败', cancelled: '已取消' }[s] || s
}

export function statusType(s) {
  return { pending: 'info', queued: 'info', processing: 'warning', completed: 'success', failed: 'danger', cancelled: 'info' }[s] || 'info'
}

export function formatTime(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('zh-CN')
}
