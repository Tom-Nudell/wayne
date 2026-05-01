import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  server: {
    headers: {
      // Required for SharedArrayBuffer (DuckDB-WASM full perf path).
      // Mirror these on the production CDN; vite serves them in dev.
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp'
    }
  }
});
