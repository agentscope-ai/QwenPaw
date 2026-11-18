import {
  cpSync,
  existsSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { expect, it } from "vitest";

it("builds the release entry at a filesystem path containing spaces and Unicode", () => {
  const temp = mkdtempSync(join(tmpdir(), "qwenpaw 空格 "));
  try {
    const frontend = join(temp, "plugin/frontend");
    mkdirSync(frontend, { recursive: true });
    for (const path of ["scripts", "src", "package.json"])
      cpSync(resolve(path), join(frontend, path), { recursive: true });
    cpSync(resolve("../examples"), join(temp, "plugin/examples"), {
      recursive: true,
    });
    symlinkSync(
      resolve("node_modules"),
      join(frontend, "node_modules"),
      "junction",
    );
    const result = spawnSync(process.execPath, ["scripts/build.mjs"], {
      cwd: frontend,
      encoding: "utf8",
      timeout: 25000,
    });
    expect(result.status, result.stderr).toBe(0);
    const dist = join(temp, "plugin/dist");
    expect(existsSync(join(dist, "index.js"))).toBe(true);
    expect(readFileSync(join(dist, "system-prompt.txt"), "utf8")).toContain(
      "Form(name, buttons, fields)",
    );
  } finally {
    rmSync(temp, { recursive: true, force: true });
  }
}, 30000);
