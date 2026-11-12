import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { harnessViteConfig } from "../../_shared/vite";

export default defineConfig(
  harnessViteConfig(import.meta.url, react({ jsxRuntime: "classic" })),
);
