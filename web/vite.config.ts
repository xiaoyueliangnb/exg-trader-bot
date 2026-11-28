import { fileURLToPath, URL } from "node:url";
import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

const src = fileURLToPath(new URL("./src/", import.meta.url));

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: [
      {
        find: /^@\//,
        replacement: src.endsWith("/") ? src : `${src}/`,
      },
    ],
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8787" },
  },
  build: {
    chunkSizeWarningLimit: 900,
  },
});
