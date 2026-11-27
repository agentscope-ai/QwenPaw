import { readFileSync } from "node:fs";
import type { Plugin as OptimizerPlugin } from "esbuild";
import type { Plugin } from "vite";

const sdkMarkdownPath =
  /[\\/]@agentscope-ai[\\/]chat[\\/]lib[\\/]Markdown[\\/]Markdown\.js$/;
const monacoMarkedPath =
  /[\\/]monaco-editor[\\/]esm[\\/]vs[\\/]base[\\/]common[\\/]marked[\\/]marked\.js$/;
const patchedMarkdownPaths = new RegExp(
  [sdkMarkdownPath, monacoMarkedPath]
    .map((pattern) => pattern.source)
    .join("|"),
);

function replaceVendorCode(
  source: string,
  needle: string,
  replacement: string,
  target: string,
): string {
  if (!source.includes(needle)) {
    throw new Error(
      `Recheck the QwenPaw double-tilde strikethrough patch against ${target}.`,
    );
  }
  return source.replace(needle, replacement);
}

// @agentscope-ai/chat's Markdown does not expose XMarkdown's `config` prop,
// and Monaco bundles its own marked copy for hover Markdown. Tighten both so
// only GFM double-tilde (`~~...~~`) delimiters trigger strikethrough and
// single `~` characters (e.g. `600~1500 t/s`) stay literal.
function loadMarkdownStrikethroughPatch(id: string): string | undefined {
  const cleanId = id.split("?")[0];
  if (sdkMarkdownPath.test(cleanId)) {
    const source = readFileSync(cleanId, "utf8");
    return replaceVendorCode(
      source,
      "      extensions: extensions,\n      walkTokens: walkTokens\n    },",
      `      extensions: extensions,
      walkTokens: walkTokens,
      tokenizer: {
        del: function del(src) {
          return src.startsWith('~~') ? false : undefined;
        }
      }
    },`,
      "@agentscope-ai/chat Markdown",
    );
  }
  if (monacoMarkedPath.test(cleanId)) {
    const source = readFileSync(cleanId, "utf8");
    return replaceVendorCode(
      source,
      "    del: /^(~~?)(?=[^\\s~])([\\s\\S]*?[^\\s~])\\1(?=[^~]|$)/,",
      "    del: /^(~~)(?=[^\\s~])([\\s\\S]*?[^\\s~])\\1(?=[^~]|$)/,",
      "monaco-editor marked",
    );
  }
  return undefined;
}

export const markdownStrikethroughPlugin: Plugin = {
  // The optimizer uses the plugin name in its dependency cache key.
  name: "qwenpaw-markdown-double-tilde-strikethrough-v1",
  enforce: "pre",
  load: loadMarkdownStrikethroughPatch,
};

// Vite's dependency pre-bundle does not run the regular load hook.
export const markdownStrikethroughOptimizer: OptimizerPlugin = {
  name: markdownStrikethroughPlugin.name,
  setup(build) {
    build.onLoad({ filter: patchedMarkdownPaths }, ({ path }) => ({
      contents: loadMarkdownStrikethroughPatch(path),
    }));
  },
};
