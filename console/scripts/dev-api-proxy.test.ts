import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { describe, expect, it } from "vitest";

const runNode = promisify(execFile);
// Load the actual config in Node: esbuild cannot run in jsdom's realm.
const script = `
  import { loadConfigFromFile } from "vite";
  const loaded = await loadConfigFromFile(
    { command: "serve", mode: "development" }, "vite.config.ts",
  );
  process.stdout.write(JSON.stringify({
    proxy: loaded?.config.server?.proxy?.["/api"],
    definedBase: loaded?.config.define?.VITE_API_BASE_URL,
  }));
`;

describe("development API proxy", () => {
  it.each([
    ["http://localhost:8001", "http://localhost:8001"],
    ["http://127.0.0.1:8001", "http://127.0.0.1:8001"],
    ["https://api.example.test", "https://api.example.test"],
    ["http://localhost:8001/backend", "http://localhost:8001/backend"],
    ["", "http://localhost:8088"],
    ["/backend", "http://localhost:8088"],
  ])("uses the configured backend for %j", async (base, target) => {
    const { stdout } = await runNode(
      process.execPath,
      ["--input-type=module", "-e", script],
      {
        cwd: process.cwd(),
        env: { ...process.env, VITE_API_BASE_URL: base },
      },
    );
    const loaded = JSON.parse(stdout);
    expect(loaded.proxy).toMatchObject({
      target,
      changeOrigin: false,
    });
    expect(loaded.definedBase).toBe(JSON.stringify(base));
  });
});
