import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { API_PREFIX } from "../kira-contracts/contract.ts";

const engine = process.env.KIRA_ENGINE ?? "http://127.0.0.1:8901";
const workspaceRoot = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig({
  // The engine mounts the built bundle under /chat/, so asset URLs have to agree.
  base: "/chat/",
  plugins: [react()],
  resolve: {
    // kira-contracts is a sibling package, outside this vite root.
    preserveSymlinks: false,
  },
  server: {
    port: 5173,
    fs: { allow: [workspaceRoot] },
    proxy: {
      // From the contract, so a namespace bump cannot leave the dev server proxying the old one.
      [API_PREFIX]: engine,
      "/healthz": engine,
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test-setup.ts"],
    restoreMocks: true,
    // One jsdom per file, and the last one is created while the others still hold theirs. The default 5 s
    // covers a test and not that queue: a screen test that passes alone has failed a full run for
    // spending the whole budget before the page existed.
    testTimeout: 20000,
    hookTimeout: 20000,
  },
});
