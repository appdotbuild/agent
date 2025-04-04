import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import tsconfigPaths from 'vite-tsconfig-paths';

// Get backend URL from environment or default to localhost for local development
const backendUrl = process.env.BACKEND_URL || 'http://localhost:2022';

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), tsconfigPaths()],
  server: {
    host: '0.0.0.0',
    proxy: {
      '/api': {
        target: backendUrl,
        rewrite: (path) => {
          if (path.startsWith('/api/')) {
            // Remove the /api prefix when forwarding to backend
            return path.replace('/api', '');
          }
          return path;
        },
        configure: (proxy) => {
          proxy.on('proxyReq', (proxyReq, req) => {
            console.log(`Proxying ${req.method} ${req.url} to backend`);
          });
        },
      },
    },
  },
});
