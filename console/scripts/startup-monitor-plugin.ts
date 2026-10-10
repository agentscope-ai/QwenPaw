import { readFile } from "node:fs/promises";
import { basename } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import type { Plugin } from "vite";

/** Inline a dependency-free monitor before Vite's entry module executes. */
export function startupMonitorPlugin(): Plugin {
  return {
    name: "console-startup-monitor",
    transformIndexHtml: {
      order: "pre",
      async handler(_html, context) {
        if (basename(context.filename) !== "index.html") return;
        const directory = new URL("../src/", import.meta.url);
        const languages = ["en", "zh", "ja", "ru", "pt-BR", "id", "vi"];
        const messages = Object.fromEntries(
          await Promise.all(
            languages.map(async (language) => {
              const locale = JSON.parse(
                await readFile(
                  new URL(`locales/${language}.json`, directory),
                  "utf8",
                ),
              );
              const {
                startup,
                reload,
                details,
                copy,
                copied,
                copyFailed,
                checking,
                recheckNote,
                observations,
              } = locale.chunkError;
              return [
                language,
                {
                  startup,
                  reload,
                  details,
                  copy,
                  copied,
                  copyFailed,
                  checking,
                  recheckNote,
                  observations,
                },
              ];
            }),
          ),
        );
        const result = await build({
          stdin: {
            contents: `import { installStartupMonitor } from "./startup/monitor";\ninstallStartupMonitor(${JSON.stringify(
              messages,
            )});`,
            resolveDir: fileURLToPath(directory),
            sourcefile: "console-startup-monitor.ts",
            loader: "ts",
          },
          bundle: true,
          write: false,
          format: "iife",
          target: "es2020",
          minify: true,
        });
        return [
          {
            tag: "script",
            children: result.outputFiles[0].text.replace(
              /<\/script/gi,
              "<\\/script",
            ),
            // Keep the charset declaration first. Module scripts are deferred,
            // so this classic script still runs before entry execution.
            injectTo: "head",
          },
        ];
      },
    },
  };
}
