import { defineConfig } from "vite";

export default defineConfig({
  server: { port: 5173 },
  build: { target: "es2022", sourcemap: true },
  // DuckDB-WASM needs cross-origin isolation for SharedArrayBuffer.
  // Toggle these headers in production via your CDN, not in the bundle.
  preview: {
    headers: {
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "require-corp",
    },
  },
});
