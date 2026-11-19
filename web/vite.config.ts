import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In development the dashboard talks to the platform started with `uvicorn`.
// Set API_TARGET if the platform listens somewhere else.
const target = process.env.API_TARGET || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, proxy: { '/api': target } },
})
