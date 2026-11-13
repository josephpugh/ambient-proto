import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the UI is served by Vite and A2A calls are proxied to the Python backend.
// In production the backend serves the built UI from frontend/dist, so the same relative paths work.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/a2a': { target: process.env.BACKEND_URL || 'http://127.0.0.1:9999', changeOrigin: true },
      '/.well-known': { target: process.env.BACKEND_URL || 'http://127.0.0.1:9999', changeOrigin: true },
    },
  },
})
