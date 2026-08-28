import assert from "node:assert/strict";
import test from "node:test";

import { normalizeThemePreference, resolveTheme } from "./model";

test("theme preference accepts explicit modes and defaults to system", () => {
  assert.equal(normalizeThemePreference("light"), "light");
  assert.equal(normalizeThemePreference("dark"), "dark");
  assert.equal(normalizeThemePreference("invalid"), "system");
  assert.equal(normalizeThemePreference(null), "system");
});

test("system theme resolves without overriding an explicit preference", () => {
  assert.equal(resolveTheme("system", "dark"), "dark");
  assert.equal(resolveTheme("system", null), "light");
  assert.equal(resolveTheme("light", "dark"), "light");
  assert.equal(resolveTheme("dark", "light"), "dark");
});
