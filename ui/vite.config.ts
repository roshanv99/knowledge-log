import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Port 5180 avoids Wardrobe Log (5173). /api goes to the Django dev server.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5180,
    strictPort: true,
    proxy: { '/api': process.env.KL_API_TARGET ?? 'http://localhost:8010' },
  },
})
