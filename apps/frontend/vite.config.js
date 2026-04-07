import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1',
    port: 5182,
    strictPort: true,
    hmr: {
      host: '127.0.0.1',
      port: 5182,
      clientPort: 5182,
      protocol: 'ws',
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 5182,
    strictPort: true,
  },
})
