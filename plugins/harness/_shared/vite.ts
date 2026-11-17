import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// The caller supplies Vite's React plugin; build dependencies belong to each leaf.
export function harnessViteConfig<T>(frontendUrl: string, reactPlugin: T) {
  const require = createRequire(frontendUrl);
  const frontendDir = dirname(fileURLToPath(frontendUrl));
  const sharedDir = dirname(fileURLToPath(import.meta.url));
  const lucideDir = dirname(require.resolve("lucide-react/package.json"));
  return {
    plugins: [reactPlugin],
    resolve: {
      alias: [
        {
          find: /^@qwenpaw\/plugin-sdk$/,
          replacement: require.resolve("@qwenpaw/plugin-sdk"),
        },
        {
          find: /^lucide-react$/,
          replacement: resolve(lucideDir, "dist/esm/lucide-react.js"),
        },
        { find: /^react$/, replacement: resolve(sharedDir, "ui/hostReact.ts") },
      ],
    },
    build: {
      lib: {
        entry: resolve(frontendDir, "src/index.tsx"),
        formats: ["es" as const],
        fileName: () => "index.js",
      },
      outDir: resolve(frontendDir, "dist"),
      emptyOutDir: true,
    },
  };
}
