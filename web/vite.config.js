import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built into the package's static folder and served same-origin by `edgefeed serve`.
// `npm run dev` proxies the API to a local `edgefeed serve` on :8090.
export default defineConfig({
  plugins: [react()],
  base: '/',
  build: { outDir: '../src/edgefeed/static', emptyOutDir: true, sourcemap: false },
  server: { proxy: { '/api': 'http://localhost:8090', '/healthz': 'http://localhost:8090' } },
})
