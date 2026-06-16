import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");

function readRepo(relativePath: string): string {
  return readFileSync(join(repoRoot, relativePath), "utf8");
}

describe("rule integrity host integration contracts (RI-SUI-HOST)", () => {
  it("MainLayout mounts GlobalRuleIntegrityRepairBanner below Header", () => {
    const mainLayout = readRepo("console/src/layouts/MainLayout/index.tsx");

    expect(mainLayout).toMatch(/import\s+\{[^}]*GlobalRuleIntegrityRepairBanner/);
    expect(mainLayout).toMatch(/<GlobalRuleIntegrityRepairBanner\s*\/>/);
    expect(mainLayout.indexOf("<Header />")).toBeGreaterThan(-1);
    expect(mainLayout.indexOf("<GlobalRuleIntegrityRepairBanner")).toBeGreaterThan(
      mainLayout.indexOf("<Header />"),
    );
  });

  it("Security page does not mount a duplicate repair banner", () => {
    const securityPage = readRepo("console/src/pages/Settings/Security/index.tsx");

    expect(securityPage).not.toMatch(/RuleIntegrityRepairBanner/);
  });

  it("extension public index exports global repair banner host", () => {
    const indexSource = readRepo("console/src/extension/rule_integrity/index.ts");

    expect(indexSource).toContain("GlobalRuleIntegrityRepairBanner");
    expect(indexSource).toContain("RuleIntegrityRepairBanner");
  });
});
