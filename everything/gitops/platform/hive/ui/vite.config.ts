import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

const apiTarget = process.env.VITE_API_TARGET ?? 'http://localhost:8100'
const containerTarget = process.env.VITE_CONTAINER_TARGET ?? 'http://localhost:8104'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      // 정본 schema는 hive 의 .claude/schemas 에 있고 빌드용으로 ./schemas 에 동기화됨 (SSOT 후 sync).
      '@schemas': path.resolve(__dirname, './schemas'),
    },
  },
  server: {
    allowedHosts: true,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
        ws: true,
        rewrite: (p) => p.replace(/^\/api/, ''),
      },
      '/container': {
        target: containerTarget,
        changeOrigin: true,
        ws: true,
        rewrite: (p) => p.replace(/^\/container/, ''),
      },
    },
  },
})
