import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: '../static/dist',
    emptyOutDir: true
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    strictPort: true,
    proxy: {
      // 脚本/下载器接口统一打到主服务 8080，由主服务网关转发到独立下载器（8092）。
      // 这样开发/生产行为一致，且主服务不直接执行脚本代码。
      '/api': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true,
        headers: {
          'Connection': 'keep-alive'
        }
      },
      '/thumbnail': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      },
      '/local_video': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      },
      '/gallery-page': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      },
      '/gallery-cover': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      },
      '/resource-file': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      }
    }
  }
})
