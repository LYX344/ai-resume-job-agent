import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, ".", "");
  const host = env.VITE_DEV_HOST || "127.0.0.1";
  const port = Number.parseInt(env.VITE_DEV_PORT || "5173", 10);
  const proxyTarget = env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8025";

  return {
    plugins: [react()],
    server: {
      host,
      port,
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true
        }
      }
    }
  };
});
