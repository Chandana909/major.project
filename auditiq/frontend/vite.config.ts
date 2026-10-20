import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const REACT = /[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom|cookie|set-cookie-parser)[\\/]/;

// The API runs on port 8000 (`python -m auditiq serve`); the development server forwards /api to it.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: true } },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    chunkSizeWarningLimit: 1600,
    rollupOptions: {
      output: {
        // React and the router in one chunk; every other package (three.js, React Three Fiber, drei and what
        // they use) in another, which loads only with a page that draws a 3D view. Both are cached apart
        // from the application code.
        manualChunks(id) {
          if (id.includes("vite/preload-helper")) return "react";   // used by every lazy page, so not in the 3D chunk
          if (!id.includes("node_modules")) return undefined;
          return REACT.test(id) ? "react" : "three";
        },
      },
    },
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"], // the browser tests in e2e/ run with Playwright (npm run e2e)
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    globals: false,
    restoreMocks: true,
    unstubGlobals: true,
    // Node loads React Three Fiber and drei as CommonJS, which require three.cjs; the application's own
    // imports are pointed at the same file so that the tests run one copy of three.js, as the browser does.
    alias: [{ find: /^three$/, replacement: fileURLToPath(new URL("./node_modules/three/build/three.cjs", import.meta.url)) }],
  },
});
