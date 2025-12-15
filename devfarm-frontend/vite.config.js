/* eslint-env node */
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const root = new URL('.', import.meta.url).pathname
  const env = loadEnv(mode, root, '')
  const target = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'
  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/device-manager': {
          target,
          changeOrigin: true,
          ws: true,
        },
        '/gitlab': {
          target,
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})
