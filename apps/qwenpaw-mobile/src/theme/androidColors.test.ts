import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const themeDir = dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);
const {
  darkColors,
  lightColors,
} = require("../../plugins/withQwenPawAndroidColors");
const tokens = readFileSync(resolve(themeDir, "tokens.ts"), "utf8");

test("Android semantic colors use app-owned light and dark resources", () => {
  assert.doesNotMatch(tokens, /\?(?:android:)?attr\//);

  const resources = [
    ...tokens.matchAll(/@color\/(qwenpaw_[a-z_]+)/g),
  ].map((match) => match[1]);

  assert.ok(resources.length > 0);
  assert.equal(new Set(resources).size, resources.length);

  for (const resource of resources) {
    assert.ok(lightColors[resource], `${resource} missing in light mode`);
    assert.ok(darkColors[resource], `${resource} missing in dark mode`);
  }
});
