import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

describe("SkillPoolSecureImportButton wiring", () => {
  it("exports a host-composable secure import control", () => {
    const componentPath = path.resolve(
      __dirname,
      "../components/SkillPoolSecureImportButton.tsx",
    );
    const source = readFileSync(componentPath, "utf8");
    expect(source).toContain("skillPool.secureImport");
    expect(source).toContain("accept=\".zip,.sig\"");
  });
});
