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
       const renderBuiltUrl = config.experimental?.renderBuiltUrl;
       process.stdout.write(JSON.stringify({
         base: config.base ?? "/",
         apiBase: config.define.VITE_API_BASE_URL,
         assetBase: config.define["import.meta.env.BASE_URL"],
         jsAsset: renderBuiltUrl?.("logo-light.svg", { hostType: "js" }),
         htmlEntry: renderBuiltUrl?.("assets/index.js", { hostType: "html" }),
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
    jsAsset?: { runtime: string };
    htmlEntry?: { relative: boolean };
    assetBase?: string;
  };
}

describe("console deployment configuration", () => {
  it.each([undefined, "", " "])(
    "uses relative entry assets when the basename is %j",
    (basename) => {
      const config = loadDeploymentConfig(basename);
      expect(config.base).toBe("./");
      expect(config.jsAsset?.runtime).toContain("__qpBase");
      expect(config.assetBase).toContain("__qpBase");
      expect(config.htmlEntry).toEqual({ relative: true });
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
