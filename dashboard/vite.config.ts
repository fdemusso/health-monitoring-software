import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: true }, // also on the network (the "Network" URL), to open the dashboard from a phone or another PC
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
})
