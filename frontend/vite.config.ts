import { fileURLToPath, URL } from 'node:url';

import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
// defineConfig comes from vitest/config, not vite: only that overload accepts the
// `test` block below. Importing vite's version makes `tsc` reject this file.
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      // Proxying keeps the browser origin identical for app and API during
      // development, so CORS behaviour in dev matches production deployment
      // behind a single origin.
      '/api': {
        target: 'http://localhost:8010',
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    css: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      include: ['src/**/*.{ts,tsx}'],
      exclude: ['src/test/**', 'src/types/api.generated.ts', 'src/main.tsx'],
    },
  },
});
