import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// base=/app/：生产环境由 FastAPI 把 dist 挂在 /app 下（过渡期），旧 Jinja 页面还在 /
export default defineConfig({
  plugins: [react()],
  base: '/app/',
  server: {
    port: 5173,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
})
