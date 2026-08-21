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
      // 代理统一打到主服务的 HTTPS 端口（443）；secure:false 以接受自签名证书。
      // 脚本/下载器接口仍由主服务网关转发到独立下载器（8092）。
      '/api': {
        target: 'https://127.0.0.1:443',
        changeOrigin: true,
        secure: false,
        headers: {
          'Connection': 'keep-alive'
        },
        // SSE 流式响应（如 AI 对话 thinking 事件）需要关闭 Vite/Node.js 代理层的缓冲。
        // http-proxy 默认对响应体做 pipe 转发（理论上流式），但 Vite dev server 的中间件链
        // 可能在更高层引入缓冲（尤其对无 Content-Length 的长连接 SSE 响应），
        // 导致所有事件积攒到连接关闭才一次性转发到前端——用户在运行中看不到思考过程。
        //
        // 修复策略：
        //   1) selfHandleResponse=true 禁止 http-proxy 自动 pipe 响应体；
        //   2) 在 proxyRes 回调里手动把 res pipe 到前端（保持流式）；
        //   3) 同时设置 no-cache / X-Accel-Buffering:no 防止任何中间层二次缓冲。
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes, req, res) => {
            const ct = (proxyRes.headers['content-type'] || '').toLowerCase()
            if (ct.includes('text/event-stream') || ct.includes('application/x-ndjson')) {
              // 标记为 SSE 流式：禁止任何层缓冲
              proxyRes.headers['cache-control'] = 'no-cache, no-transform'
              proxyRes.headers['x-accel-buffering'] = 'no'
              // 手动 pipe 保持逐 chunk 流式（替代 http-proxy 默认的自动 pipe）
              if (!res.headersSent) res.writeHead(proxyRes.statusCode, proxyRes.headers)
              return proxyRes.pipe(res)
            }
          })
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
