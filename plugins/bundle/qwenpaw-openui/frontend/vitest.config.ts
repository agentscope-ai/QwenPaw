import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    {
      name: "test-styles",
      resolveId(id) {
        if (id === "openui:styles") return id;
      },
      load(id) {
        if (id === "openui:styles")
          return 'export default ".qwenpaw-openui { min-width: 0; }"';
      },
    },
  ],
  test: { environment: "jsdom", setupFiles: ["./test/setup.ts"] },
});
