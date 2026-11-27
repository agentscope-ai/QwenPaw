import { execFileSync } from "node:child_process";
import { describe, expect, it } from "vitest";

function loadDeploymentConfig(basename: string | undefined) {
  const env: NodeJS.ProcessEnv = {
    ...process.env,
    BASE_URL: "https://unrelated.example.com",
    VITE_API_BASE_URL: "/backend",
  };
  delete env.VITE_CONSOLE_BASENAME;
  if (basename !== undefined) env.VITE_CONSOLE_BASENAME = basename;

  // Load build tooling in Node, outside jsdom's browser globals.
  const output = execFileSync(
    process.execPath,
    [
      "--input-type=module",
      "--eval",
      `import { loadConfigFromFile } from "vite";
       const { config } = await loadConfigFromFile({
         command: "build", mode: "production",
       });
       const document = config.plugins.find(p => p.name === "console-host-document");
       process.stdout.write(JSON.stringify({
         base: config.base ?? "/",
         html: document.transformIndexHtml("<head></head>"),
         apiBase: config.define.VITE_API_BASE_URL,
       }));`,
    ],
    {
      env,
      encoding: "utf8",
    },
  );
  return JSON.parse(output) as { base: string; html: string; apiBase: string };
}

describe("console deployment configuration", () => {
  it.each([undefined, "", " "])(
    "keeps assets at the root when the basename is %j",
    (basename) => {
      const config = loadDeploymentConfig(basename);
      expect(config.base).toBe("./");
      expect(config.html).toContain('<base href="/">');
    },
  );

  it.each([
    ["/qwenpaw", "/qwenpaw/"],
    ["/qwenpaw/", "/qwenpaw/"],
    ["qwenpaw", "/qwenpaw/"],
    [" /apps/qwenpaw// ", "/apps/qwenpaw/"],
    ["/", "/"],
  ])("uses %j as the asset prefix %j", (basename, base) => {
    const config = loadDeploymentConfig(basename);
    expect(config.base).toBe(base);
    expect(config.html).toContain(`<base href="${base}">`);
    expect(config.apiBase).toBe('"/backend"');
  });
});
