import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // 开发时把 /api/** 代理到 FastAPI，避免跨域
      "/api": {
        target: "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
});
