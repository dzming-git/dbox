import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs'

// https://vite.dev/config/
// 后端主服务已启用 HTTPS（自签名证书，端口 443）并禁用明文 HTTP（呼应反馈 202608090002）。
// 前端 dev server 也开启 HTTPS，使整个应用访问链路均为 HTTPS。
// 证书由后端自动生成在用户数据区（默认 %ProgramData%\Dbox\config），
// 通过环境变量动态定位，避免硬编码绝对路径；secure:false 以接受自签名证书。
const certDir = process.env.DBOX_CERT_DIR
  || path.join(process.env.ProgramData || 'C:\\ProgramData', 'Dbox', 'config')
const certFile = path.join(certDir, 'dbox-selfsigned.crt')
const keyFile = path.join(certDir, 'dbox-selfsigned.key')
const https = fs.existsSync(certFile) && fs.existsSync(keyFile)
  ? { cert: certFile, key: keyFile }
  : true

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
    https,
    proxy: {
      // 插件扩展接口（/api/ext/*）直接代理到拓展管理宿主（8093）。
      // 主服务（443）用 Python requests 反代 SSE 时，即使扩展宿主已立即发送响应头，
      // requests 在读取 Flask 开发服务器的分块 SSE 响应头阶段仍会阻塞（库层面的兼容问题），
      // 导致 CodeBuddy流式回复每次都“连接中断，请重试”。由 Vite（Node http-proxy）直接转发
      // SSE 可正常工作（扩展宿主侧已通过先 yield 注释块确保响应头即时发出）。
      '/api/ext': {
        target: 'http://127.0.0.1:8093',
        changeOrigin: true,
        secure: false
      },
      // 代理统一打到主服务的 HTTPS 端口（443）；secure:false 以接受自签名证书。
      // 脚本/下载器接口仍由主服务网关转发到独立下载器（8092）。
      '/api': {
        target: 'https://127.0.0.1:443',
        changeOrigin: true,
        secure: false,
        headers: {
          'Connection': 'keep-alive'
        }
      },
      '/thumbnail': {
        target: 'https://127.0.0.1:443',
        changeOrigin: true,
        secure: false
      },
      '/local_video': {
        target: 'https://127.0.0.1:443',
        changeOrigin: true,
        secure: false
      },
      '/gallery-page': {
        target: 'https://127.0.0.1:443',
        changeOrigin: true,
        secure: false
      },
      '/gallery-cover': {
        target: 'https://127.0.0.1:443',
        changeOrigin: true,
        secure: false
      },
      '/resource-file': {
        target: 'https://127.0.0.1:443',
        changeOrigin: true,
        secure: false
      }
    }
  }
})
