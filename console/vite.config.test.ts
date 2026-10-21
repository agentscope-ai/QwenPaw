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
       process.stdout.write(JSON.stringify({
         base: config.base ?? "/",
         apiBase: config.define.VITE_API_BASE_URL,
       }));`,
    ],
    {
      env,
      encoding: "utf8",
    },
  );
  return JSON.parse(output) as { base: string; apiBase: string };
}

describe("console deployment configuration", () => {
  it.each([undefined, "", " "])(
    "keeps assets at the root when the basename is %j",
    (basename) => {
      const config = loadDeploymentConfig(basename);
      expect(config.base).toBe("/");
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
    expect(config.apiBase).toBe('"/backend"');
  });
});
