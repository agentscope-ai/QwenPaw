import { build } from "esbuild";
import postcss from "postcss";
import { fileURLToPath } from "node:url";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import React from "react";
import ReactDOM from "react-dom";
import { openuiLibrary, openuiPromptOptions } from "@openuidev/react-ui";

const outDir = new URL("../../dist/", import.meta.url);
await mkdir(outDir, { recursive: true });

const example = await readFile(
  new URL("../../examples/seeds.openui", import.meta.url),
  "utf8",
);
const inline = `## Inline Mode

You are answering in QwenPaw Chat. Use interactive UI only when interaction improves the answer.
Ordinary Markdown, images, and complete openui-lang fenced blocks may alternate in one reply.
Plain-text answers are welcome. Put only active UI in triple-backtick openui-lang fences.
For code explanations/examples, use an outer four-backtick text fence so the example stays inert.
Each UI fence is an independent, complete program with its own root and local state.
Never reference another fence or an earlier reply. Never output patches; changes produce a NEW complete UI in the new reply.
Keep reactive text and derived values inside the same UI block as their controls.
UI renders progressively while the fence is still open. Write root first, then state,
then referenced components in display order so useful content appears early.
Always declare a state variable before the first component that uses it.
Use $variables for local interactions. @Set and @Reset run locally without calling the assistant.
@ToAssistant must include the selected values in its message or explicit context argument.
Local edits are not automatically visible to the assistant and reset when the page is refreshed.
Only @ToAssistant and @OpenUrl (absolute HTTP(S) links) are supported host actions.
No Query, Mutation, @Run, tool calls, script bundles, HTML, JavaScript, browser APIs or eval.
The only executable language is openui-lang using the following registered component catalog.
`;
let prompt = openuiLibrary.prompt({
  ...openuiPromptOptions,
  preamble:
    "You are a helpful assistant. You may include interactive openui-lang UI inline in your Markdown replies when useful.",
  inlineMode: true,
  bindings: true,
  toolCalls: false,
  editMode: false,
  examples: [example],
  additionalRules: [
    ...openuiPromptOptions.additionalRules.filter(
      (rule) => !/query|queries|@Run|realistic\/plausible/i.test(rule),
    ),
    "Use supplied or verified data. Label illustrative sample data explicitly; never invent factual results.",
  ],
});
// Adapt the pinned upstream protocol to the host's block-level lifecycle.
// Fail on upstream wording changes so dependency upgrades require review.
function replaceOnce(text, before, after) {
  if (text.split(before).length !== 2)
    throw new Error(`Upstream prompt changed: ${before}`);
  return text.replace(before, after);
}
function replaceSection(text, heading, replacement) {
  const start = text.indexOf(heading);
  if (start < 0) throw new Error(`Upstream prompt section missing: ${heading}`);
  const end = text.indexOf("\n## ", start + heading.length);
  return text.slice(0, start) + replacement + (end < 0 ? "" : text.slice(end));
}
prompt = replaceSection(prompt, "## Inline Mode", inline);
for (const [before, after] of [
  [
    "Always pass a Buttons(...) reference as the third Form argument.",
    "Always pass a Buttons(...) reference as the second Form argument: Form(name, buttons, fields).",
  ],
  [
    "passed to the assistant as hidden data",
    "included as JSON in the visible user message",
  ],
])
  prompt = replaceOnce(prompt, before, after);
if (
  /ONLY the changed\/new statements|ENTIRE response must|hidden data/.test(
    prompt,
  )
)
  throw new Error("Conflicting host instructions in the generated prompt.");

// The public SDK recommends a local type snapshot for standalone plugins.
// Check it when building inside QwenPaw; standalone archives need no host tree.
try {
  const publicTypes = await readFile(
    new URL(
      "../../../../../console/src/plugins/types/qwenpaw.d.ts",
      import.meta.url,
    ),
    "utf8",
  );
  const localTypes = await readFile(
    new URL("../src/qwenpaw-host.d.ts", import.meta.url),
    "utf8",
  );
  if (
    publicTypes.includes("export interface ChatCodeBlockProps") &&
    publicTypes !== localTypes
  )
    throw new Error(
      "Host SDK types changed; refresh src/qwenpaw-host.d.ts from console/src/plugins/types/qwenpaw.d.ts.",
    );
} catch (error) {
  if (error.code !== "ENOENT") throw error;
}
await writeFile(new URL("system-prompt.txt", outDir), prompt);

const css = await build({
  entryPoints: ["src/components.css"],
  bundle: true,
  write: false,
  minify: true,
  loader: {
    ".woff": "dataurl",
    ".woff2": "dataurl",
    ".ttf": "dataurl",
    ".svg": "dataurl",
  },
});
const scope = ':where(.qwenpaw-openui, [class*="openui-theme-portal-"])';
const root = postcss.parse(css.outputFiles[0].text);
root.walkRules((rule) => {
  // Keyframe percentages are not DOM selectors.
  if (rule.parent?.type === "atrule" && /keyframes$/i.test(rule.parent.name))
    return;
  rule.selectors = rule.selectors.flatMap((selector) => {
    if (selector === ":root" || selector === "body" || selector === "html")
      return [scope];
    return [`${scope} ${selector}`, `${scope}:is(${selector})`];
  });
});
const styles =
  root.toString() +
  `
.qwenpaw-openui { min-width: 0; max-width: 100%; margin: 12px 0; }
.qwenpaw-openui-content { margin: 0; padding: 0; border: 0; min-width: 0; }
.qwenpaw-openui-progress { min-height: 24px; margin-top: 8px; opacity: 0.65; }
.qwenpaw-openui [role="alert"] { overflow-wrap: anywhere; }
`;

const result = await build({
  entryPoints: ["src/index.tsx"],
  outfile: fileURLToPath(new URL("index.js", outDir)),
  bundle: true,
  format: "esm",
  platform: "browser",
  target: "es2022",
  minify: true,
  metafile: true,
  jsx: "automatic",
  define: { "process.env.NODE_ENV": '"production"' },
  plugins: [
    {
      name: "qwenpaw-host",
      setup(builder) {
        // OpenUI uses Prism's inline palette. Its public CSS mode retains
        // token classes so one scoped theme covers standalone and nested code.
        builder.onResolve(
          { filter: /^react-syntax-highlighter$/ },
          ({ namespace }) =>
            namespace === "qwenpaw"
              ? undefined
              : { path: "syntax-highlighter", namespace: "qwenpaw" },
        );
        builder.onResolve(
          { filter: /^(react|react-dom|openui:styles)$/ },
          ({ path }) => ({ path, namespace: "qwenpaw" }),
        );
        builder.onLoad({ filter: /.*/, namespace: "qwenpaw" }, ({ path }) => {
          if (path === "openui:styles")
            return { contents: `export default ${JSON.stringify(styles)}` };
          if (path === "syntax-highlighter")
            return {
              contents: `import { createElement } from "react";
                import { Prism as BasePrism } from "react-syntax-highlighter";
                export const Prism = (props) => createElement(BasePrism, {
                  ...props, useInlineStyles: false,
                  codeTagProps: props.codeTagProps ?? { className: props.language && "language-" + props.language }
                });`,
              resolveDir: fileURLToPath(new URL("../", import.meta.url)),
            };
          const name = path === "react" ? "React" : "ReactDOM";
          const exports = Object.keys(
            path === "react" ? React : ReactDOM,
          ).filter((key) => key !== "default");
          return {
            contents: `const host = window.QwenPaw.host.${name}; export default host; export const {${exports.join(
              ",",
            )}} = host;`,
          };
        });
      },
    },
  ],
});
const output = Object.values(result.metafile.outputs);
if (output.some((item) => item.imports.length))
  throw new Error("Plugin must be a self-contained ES module.");
console.log(
  `OpenUI built: ${output.reduce(
    (n, item) => n + item.bytes,
    0,
  )} bytes; prompt ${prompt.length} characters.`,
);
