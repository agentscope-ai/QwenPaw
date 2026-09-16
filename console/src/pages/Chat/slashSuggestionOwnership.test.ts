import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const chatPageSource = readFileSync(
  path.resolve(process.cwd(), "src/pages/Chat/index.tsx"),
  "utf-8",
);

describe("slash suggestion ownership", () => {
  it("keeps slash suggestions in the custom menu instead of registering a second SDK popup", () => {
    expect(chatPageSource).toMatch(/className=\{styles\.inlineSlashMenu\}/);
    expect(chatPageSource).toMatch(/suggestions:\s*activePluginSuggestions/);
    expect(chatPageSource).not.toMatch(
      /suggestions:\s*\[\.\.\.baseSuggestions,\s*\.\.\.activePluginSuggestions\]/,
    );
  });
});
