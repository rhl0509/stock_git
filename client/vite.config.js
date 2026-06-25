import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/auth':    { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/api':     { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/price':   { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/prices':  { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/search':  { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/search-stock-kr': { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/market':     { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/recommend':  { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/ml':         { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/stock':      { target: 'http://127.0.0.1:5001', changeOrigin: true },
      '/sync-kr-stocks': { target: 'http://127.0.0.1:5001', changeOrigin: true },
    },
  },
  build: {
    outDir: '../static/spa',
    emptyOutDir: true,
  },
});
