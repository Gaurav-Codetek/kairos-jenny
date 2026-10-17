import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Pure-logic tests only (lib/**): no DOM, no React rendering.
export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    include: ["lib/**/*.test.ts"],
    environment: "node",
  },
});
