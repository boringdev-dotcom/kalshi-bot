import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  // Load env file based on mode (development, production)
  const env = loadEnv(mode, '.')
  
  // Backend URL from VITE_BACKEND_URL env var, defaults to localhost:8000
  const backendUrl = env.VITE_BACKEND_URL || 'http://localhost:8000'
  // Convert http(s) to ws(s) for WebSocket
  const backendWsUrl = backendUrl.replace(/^http/, 'ws')
  
  console.log('Proxy config:', { backendUrl, backendWsUrl })
  
  return {
    plugins: [react()],
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          secure: false, // Allow self-signed certs
        },
        '/ws': {
          target: backendWsUrl,
          ws: true,
          changeOrigin: true,
          secure: false, // Allow self-signed certs
        },
      },
    },
  }
})
