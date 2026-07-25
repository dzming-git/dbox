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
      '/api/scripts': {
        target: 'http://127.0.0.1:8082',
        changeOrigin: true,
        headers: {
          'Connection': 'keep-alive'
        }
      },
      '/api/admin/scripts': {
        target: 'http://127.0.0.1:8082',
        changeOrigin: true,
        headers: {
          'Connection': 'keep-alive'
        }
      },
      '/api/admin/cookies': {
        target: 'http://127.0.0.1:8082',
        changeOrigin: true,
        headers: {
          'Connection': 'keep-alive'
        }
      },
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
      '/comic-page': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      },
      '/comic-cover': {
        target: 'http://127.0.0.1:8080',
        changeOrigin: true
      }
    }
  }
})
