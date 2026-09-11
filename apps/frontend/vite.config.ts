/// <reference types="vitest/config" />

import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import tailwindcss from "@tailwindcss/vite";
import { codeInspectorPlugin } from "code-inspector-plugin";

export default defineConfig({
  plugins: [vue(), tailwindcss(), codeInspectorPlugin({ bundler: "vite" })],
  server: {
    host: "0.0.0.0",
    port: 5173,
    proxy: {
      "/api": {
        target:
          process.env.VITE_BACKEND_PROXY_TARGET ?? "http://127.0.0.1:8001",
        changeOrigin: true,
      },
    },
  },
  test: { environment: "node" },
});
