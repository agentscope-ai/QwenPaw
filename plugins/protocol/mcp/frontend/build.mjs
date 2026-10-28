// Build with the existing Console toolchain; never install plugin-local deps.
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(
  new URL("../../../../console/package.json", import.meta.url),
);
const { build } = require("esbuild");
await build({
  entryPoints: [fileURLToPath(new URL("./index.tsx", import.meta.url))],
  outfile: fileURLToPath(new URL("./dist/index.js", import.meta.url)),
  alias: {
    "@qwenpaw/plugin-sdk": fileURLToPath(
      new URL(
        "../../../../src/qwenpaw/plugins/frontend/index.js",
        import.meta.url,
      ),
    ),
  },
  bundle: true,
  format: "esm",
  target: "es2020",
  minify: true,
});
