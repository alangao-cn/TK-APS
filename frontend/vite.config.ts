import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// 生产环境由 FastAPI 把 dist 托管在根路径 /，单进程服务前后端
export default defineConfig({
  plugins: [react()],
  base: '/',
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
