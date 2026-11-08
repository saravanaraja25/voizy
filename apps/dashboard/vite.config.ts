/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import type { Plugin } from 'vite'

// Strict CSP for production builds only. The dev server injects styles inline for hot reload, which
// a strict style-src would block. frame-ancestors is ignored in a <meta>, so serve it as a header.
// Libraries inject three small stylesheets at run time (toast and popup styling). Rather than allow
// 'unsafe-inline', allow exactly those by hash. If a dependency upgrade changes one, the browser
// logs the new hash in a CSP violation message: replace the matching entry.
const INJECTED_STYLE_HASHES = [
  'sha256-47DEQpj8HBSa+/TImW+5JCeuQeRkm5NMpJWZG3hSuFU=',
  'sha256-StEaX+se6YS7pqjzrzMIA0KaX9zF/8zAhvQXZAe5epY=',
  'sha256-kLmvWqfziFavKtqHqRsb90f006UAK2Dmd0It5Iz2KFA=',
]

const CSP = [
  "default-src 'self'",
  "script-src 'self'",
  `style-src 'self' ${INJECTED_STYLE_HASHES.map((h) => `'${h}'`).join(' ')}`,
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
  server: {
    port: 5173,
    strictPort: true,
    host: '127.0.0.1',
    // One origin for the browser (same as production behind a reverse proxy): cookies stay
    // first-party and no CORS is involved. Point VOIZY_API_TARGET elsewhere if the API is not here.
    proxy: {
      '/v1': { target: process.env.VOIZY_API_TARGET ?? 'http://127.0.0.1:8010', changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
