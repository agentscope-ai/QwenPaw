import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
    plugins: [react({ jsxRuntime: "classic" })],
    define: {
        "process.env.NODE_ENV": JSON.stringify("production"),
    },
    build: {
        lib: {
            entry: "src/index.tsx",
            formats: ["es"],
            fileName: () => "index.js",
        },
        rollupOptions: {
            external: ["react", "react-dom"],
        },
    },
});
