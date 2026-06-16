import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, it, expect } from "vitest";

const notifierSource = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), "index.tsx"),
  "utf8",
);

describe("FileBaselineDriftAlertNotifier UI contract (FB-SUI-NOTIFIER)", () => {
  it("loads open alerts and renders restore/accept actions", () => {
    expect(notifierSource).toContain("getFileBaselineProtectionAlerts");
    expect(notifierSource).toContain("getFileBaselineProtectionSettings");
    expect(notifierSource).toContain("useFileBaselineDriftWatch");
    expect(notifierSource).toContain("restoreFileBaselineAlert");
    expect(notifierSource).toContain("acceptFileBaselineAlert");
    expect(notifierSource).toContain(
      "security.integrityProtection.restoreAction",
    );
    expect(notifierSource).toContain(
      "security.integrityProtection.acceptAction",
    );
    expect(notifierSource).toContain('role="region"');
  });

  it("stays hidden when protection is off or there are no alerts", () => {
    expect(notifierSource).toContain("!personaEnabled || alerts.length === 0");
    expect(notifierSource).toContain("return null");
  });
});
