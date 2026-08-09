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
      // 后端已启用 HTTPS（自签名证书，端口 8443）并禁用明文 HTTP（呼应反馈 202608090002）。
      // 前端代理统一打到主服务的 HTTPS 端口；secure:false 以接受自签名证书。
      // 脚本/下载器接口仍由主服务网关转发到独立下载器（8092）。
      '/api': {
        target: 'https://127.0.0.1:8443',
        changeOrigin: true,
        secure: false,
        headers: {
          'Connection': 'keep-alive'
        }
      },
      '/thumbnail': {
        target: 'https://127.0.0.1:8443',
        changeOrigin: true,
        secure: false
      },
      '/local_video': {
        target: 'https://127.0.0.1:8443',
        changeOrigin: true,
        secure: false
      },
      '/gallery-page': {
        target: 'https://127.0.0.1:8443',
        changeOrigin: true,
        secure: false
      },
      '/gallery-cover': {
        target: 'https://127.0.0.1:8443',
        changeOrigin: true,
        secure: false
      },
      '/resource-file': {
        target: 'https://127.0.0.1:8443',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
