import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

function loadDeploymentConfig(
  basename: string | undefined,
  mode = "production",
) {
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
         command: "build", mode: ${JSON.stringify(mode)},
       });
       process.stdout.write(JSON.stringify({
         base: config.base ?? "/",
         apiBase: config.define.VITE_API_BASE_URL,
         assetBaseOverride: config.define["import.meta.env.BASE_URL"],
         assetUrlOverride: Boolean(config.experimental?.renderBuiltUrl),
       }));`,
    ],
    {
      env,
      encoding: "utf8",
    },
  );
  return JSON.parse(output) as {
    base: string;
    apiBase: string;
    assetBaseOverride?: string;
    assetUrlOverride: boolean;
  };
}

describe("console deployment configuration", () => {
  it.each([undefined, "", " "])(
    "uses Vite's standard relative asset handling when the basename is %j",
    (basename) => {
      const config = loadDeploymentConfig(basename);
      expect(config.base).toBe("./");
      expect(config.assetUrlOverride).toBe(false);
      expect(config.assetBaseOverride).toBeUndefined();
    },
  );

  it("keeps the backend's document-base token without a base-setting script", () => {
    const html = readFileSync("index.html", "utf8");
    expect(html).toContain('<base href="/" />');
    expect(html).not.toContain("__qpBase");
  });

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
    expect(config.assetUrlOverride).toBe(false);
    expect(config.assetBaseOverride).toBeUndefined();
  });

  it("keeps the Tauri asset base at the root regardless of the web basename", () => {
    const config = loadDeploymentConfig("/qwenpaw", "tauri");
    expect(config.base).toBe("/");
    expect(config.apiBase).toBe('""');
    expect(config.assetUrlOverride).toBe(false);
    expect(config.assetBaseOverride).toBeUndefined();
  });
});
