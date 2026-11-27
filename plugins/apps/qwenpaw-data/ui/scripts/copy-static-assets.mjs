import { cpSync } from "node:fs";

// Older development checkouts can contain a generated public/context-console.
// Ship the deep-link entry point and a single copy of the released console.
for (const asset of ["app", "data-console"]) {
  cpSync(`public/${asset}`, `dist/${asset}`, { recursive: true });
}
cpSync("compat/context-console", "dist/context-console", { recursive: true });
