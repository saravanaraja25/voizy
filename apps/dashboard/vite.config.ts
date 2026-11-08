/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import type { Plugin } from 'vite'

// Strict CSP for production builds only. The dev server injects styles inline for hot reload, which
// a strict style-src would block. frame-ancestors is ignored in a <meta>, so serve it as a header.
const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "media-src 'self' blob:",
  'connect-src \'self\' https: wss:',
  "object-src 'none'",
  "base-uri 'none'",
  "form-action 'none'",
].join('; ')

const productionCsp: Plugin = {
  name: 'voizy-production-csp',
  apply: 'build',
  transformIndexHtml: (html) =>
    html.replace('</head>', `    <meta http-equiv="Content-Security-Policy" content="${CSP}" />\n  </head>`),
}

export default defineConfig({
  plugins: [react(), tailwindcss(), productionCsp],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, './src') } },
  server: { port: 5173, strictPort: true, host: '127.0.0.1' },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
