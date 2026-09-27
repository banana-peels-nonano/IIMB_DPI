import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const backendOrigin = env.VITE_MIRROR_BACKEND_ORIGIN || "http://127.0.0.1:8080";

  return {
    plugins: [react()],
    server: {
      proxy: {
        "/_mirror_backend": {
          target: backendOrigin,
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/_mirror_backend/, ""),
        },
      },
    },
  };
});
