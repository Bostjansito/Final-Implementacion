import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En desarrollo (npm run dev) se replica el proxy de nginx hacia los servicios publicados en localhost.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api/productos": { target: "http://localhost:8001", rewrite: (p) => p.replace(/^\/api\/productos/, "") },
      "/api/clientes": { target: "http://localhost:8002", rewrite: (p) => p.replace(/^\/api\/clientes/, "") },
      "/api/prestamos": { target: "http://localhost:8003", rewrite: (p) => p.replace(/^\/api\/prestamos/, "") },
      "/api/inventario": { target: "http://localhost:8004", rewrite: (p) => p.replace(/^\/api\/inventario/, "") },
    },
  },
});
