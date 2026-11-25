import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import type { Plugin } from 'vite';
import postcss from 'postcss';
import postcssCustomMedia from 'postcss-custom-media';
import type { PluginCreator } from 'postcss';
import { mockApi } from './mock/plugin.ts';

const FAVICON_SOURCE = new URL('./src/assets/brand/favicon.svg', import.meta.url);

const MEDIA_DEFINITIONS = new URL('./src/styles/media.css', import.meta.url);

const sharedMedia: PluginCreator<void> = () => ({
  postcssPlugin: 'ovenbird-shared-media',
  Once(root) {
    root.prepend(postcss.parse(readFileSync(MEDIA_DEFINITIONS, 'utf8')).nodes);
  },
});
sharedMedia.postcss = true;

function brandFavicon(): Plugin {
  return {
    name: 'brand-favicon',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (request.url?.split('?')[0] !== '/favicon.svg') return next();
        response.setHeader('Content-Type', 'image/svg+xml');
        response.end(readFileSync(FAVICON_SOURCE));
      });
    },
    generateBundle() {
      this.emitFile({
        type: 'asset',
        fileName: 'favicon.svg',
        source: readFileSync(FAVICON_SOURCE),
      });
    },
  };
}

// Unit tests format times in one fixed zone, so they read the same on every machine and CI.
if (process.env['VITEST']) process.env['TZ'] = 'Europe/Amsterdam';

export default defineConfig(({ mode }) => ({
  base: './',
  resolve: {
    alias: {
      $ui: fileURLToPath(new URL('./src/components/ui', import.meta.url)),
      $components: fileURLToPath(new URL('./src/components', import.meta.url)),
      $lib: fileURLToPath(new URL('./src/lib', import.meta.url)),
      $mock: fileURLToPath(new URL('./mock', import.meta.url)),
    },
  },
  plugins: [
    svelte(),
    brandFavicon(),
    ...(mode === 'mock' ? [mockApi()] : []),
    ...(process.env['VITEST'] ? [svelteTesting()] : []),
  ],
  css: { postcss: { plugins: [sharedMedia(), postcssCustomMedia()] } },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
  server: {
    proxy:
      mode === 'mock'
        ? undefined
        : {
            '/api': {
              target: 'http://127.0.0.1:8099',
              ws: true,
              changeOrigin: true,
              auth: process.env['OVENBIRD_PROXY_AUTH'],
              configure: (proxy) => {
                const sameOrigin = (request: {
                  getHeader(n: string): unknown;
                  setHeader(n: string, v: string): unknown;
                }) => {
                  if (request.getHeader('origin'))
                    request.setHeader('origin', 'http://127.0.0.1:8099');
                };
                proxy.on('proxyReq', sameOrigin);
                proxy.on('proxyReqWs', sameOrigin);
              },
            },
          },
  },
  test: { include: ['src/**/*.test.{ts,svelte.ts}'], environment: 'node' },
}));
