import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");

function readRepo(relativePath: string): string {
  return readFileSync(join(repoRoot, relativePath), "utf8");
}

describe("file baseline host integration contracts (FB-SUI-HOST)", () => {
  it("MainLayout mounts FileBaselineDriftAlertNotifier globally", () => {
    const mainLayout = readRepo("console/src/layouts/MainLayout/index.tsx");

    expect(mainLayout).toMatch(/import\s+FileBaselineDriftAlertNotifier/);
    expect(mainLayout).toMatch(/<FileBaselineDriftAlertNotifier\s*\/>/);
  });

  it("MainLayout mounts GlobalOperatorApprovalOverlay globally", () => {
    const mainLayout = readRepo("console/src/layouts/MainLayout/index.tsx");

    expect(mainLayout).toMatch(/GlobalOperatorApprovalOverlay/);
    expect(mainLayout).toMatch(/<GlobalOperatorApprovalOverlay\s*\/>/);
  });

  it("extension public index exports drift notifier and alert action surface", () => {
    const indexSource = readRepo("console/src/extension/file_baseline/index.ts");
    const requiredExports = [
      "FileBaselineDriftAlertNotifier",
      "GlobalOperatorApprovalOverlay",
      "useFileBaselineDriftWatch",
      "restoreFileBaselineAlert",
      "acceptFileBaselineAlert",
    ];

    for (const symbol of requiredExports) {
      expect(indexSource).toContain(symbol);
    }
  });
});
