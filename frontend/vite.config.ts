import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const API_TARGET = process.env.VITE_API_PROXY_TARGET ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { '/api': { target: API_TARGET, changeOrigin: true } },
  },
  // preview обслуживает собранный dist и НЕ наследует proxy из server.
  // Без этой секции e2e-прогон бил бы в 5173 без бэкенда, а перенос на
  // другой origin сломал бы refresh-cookie с SameSite=Strict.
  preview: {
    port: 5173,
    proxy: { '/api': { target: API_TARGET, changeOrigin: true } },
  },
  test: {
    environment: 'jsdom', globals: true,
    include: ['tests/**/*.test.{ts,tsx}'],
    setupFiles: ['tests/setup.ts'],
  },
})
