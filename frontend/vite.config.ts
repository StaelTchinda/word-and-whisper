import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Proxies API calls to `make serve` (prayer-serve, FastAPI on :8000) during
// local dev, under /api so the prefix never collides with the SPA's own web
// paths -- notably /sources/:sourceId, which is both a page route here and a
// real API path on the backend. That collision would exist at the origin
// level in any single-server deployment too, not just in this dev proxy, so
// the app always calls the backend through /api/* rather than mirroring its
// paths one-to-one.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
