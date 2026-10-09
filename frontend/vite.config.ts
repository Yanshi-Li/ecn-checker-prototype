import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:5000",
      "/upload": "http://127.0.0.1:5000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/testSetup.ts",
    restoreMocks: true,
  },
});
