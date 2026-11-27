import { resolve } from "node:path";
import type { PluginBuild } from "esbuild";
import { describe, expect, it } from "vitest";
import {
  markdownStrikethroughOptimizer,
  markdownStrikethroughPlugin,
} from "./markdown-strikethrough-plugin";

async function loadPatchedModule(path: string): Promise<string> {
  const load = markdownStrikethroughPlugin.load;
  if (typeof load !== "function") {
    throw new Error("The Markdown strikethrough patch must use a load hook.");
  }
  const result = await load.call({} as never, path, { ssr: false });
  if (typeof result !== "string") {
    throw new Error("The Markdown strikethrough patch did not return source.");
  }
  return result;
}

function loadOptimizedModule(path: string): string {
  const setup = markdownStrikethroughOptimizer.setup;
  if (typeof setup !== "function") {
    throw new Error(
      "The Markdown strikethrough optimizer must register an onLoad hook.",
    );
  }
  let handler: unknown;
  setup({
    onLoad: (_options, callback) => {
      handler = callback;
    },
  } as unknown as PluginBuild);
  if (typeof handler !== "function") {
    throw new Error(
      "The Markdown strikethrough optimizer did not register its hook.",
    );
  }
  const result = handler({ path }) as { contents?: string };
  if (typeof result.contents !== "string") {
    throw new Error(
      "The Markdown strikethrough optimizer did not return source.",
    );
  }
  return result.contents;
}

describe("markdown double-tilde strikethrough plugin", () => {
  const sdkMarkdownPath = resolve(
    process.cwd(),
    "node_modules/@agentscope-ai/chat/lib/Markdown/Markdown.js",
  );
  const monacoMarkedPath = resolve(
    process.cwd(),
    "node_modules/monaco-editor/esm/vs/base/common/marked/marked.js",
  );

  it("injects a double-tilde del tokenizer into @agentscope-ai/chat Markdown", async () => {
    const source = await loadPatchedModule(sdkMarkdownPath);

    expect(source).toContain("tokenizer:");
    expect(source).toContain("src.startsWith('~~') ? false : undefined");
  });

  it("tightens monaco-editor marked del rule to double tildes", async () => {
    const source = await loadPatchedModule(monacoMarkedPath);

    expect(source).toContain(
      "del: /^(~~)(?=[^\\s~])([\\s\\S]*?[^\\s~])\\1(?=[^~]|$)/,",
    );
    expect(source).not.toContain(
      "del: /^(~~?)(?=[^\\s~])([\\s\\S]*?[^\\s~])\\1(?=[^~]|$)/,",
    );
  });

  it("applies both patches during dependency pre-bundling", () => {
    const sdkSource = loadOptimizedModule(sdkMarkdownPath);
    const monacoSource = loadOptimizedModule(monacoMarkedPath);

    expect(sdkSource).toContain("src.startsWith('~~') ? false : undefined");
    expect(monacoSource).toContain(
      "del: /^(~~)(?=[^\\s~])([\\s\\S]*?[^\\s~])\\1(?=[^~]|$)/,",
    );
  });
});
