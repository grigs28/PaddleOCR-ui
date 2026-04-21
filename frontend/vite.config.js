import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:5553',
        changeOrigin: true,
      },
      '/auth': {
        target: 'http://localhost:5553',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://localhost:5553',
        ws: true,
      },
    },
  },
})
