import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api/v1': {
        target: process.env.PAWLOCAL_API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: { environment: 'jsdom', setupFiles: './src/test/setup.ts', css: true, include: ['src/**/*.test.{ts,tsx}'] },
})
