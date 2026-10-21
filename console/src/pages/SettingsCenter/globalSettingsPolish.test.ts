import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const read = (file: string) =>
  readFileSync(join(process.cwd(), "src", file), "utf8");

describe("global settings polish contracts", () => {
  it("uses a precise stepper for the bounded corner radius", () => {
    const source = read("pages/SettingsCenter/GeneralSettings.tsx");
    expect(source).toContain("<NumberStepper");
    expect(source).toContain('suffix="px"');
    expect(source).not.toContain("Slider,");
  });

  it("marks cards with effective status without adding a status badge", () => {
    const source = read("pages/Settings/Agents/components/AgentGallery.tsx");
    expect(source).toContain("data-agent-status={effectiveStatus}");
    expect(source).not.toContain("styles.statusBadge");
    expect(source).not.toContain("renderStatusIcon");
  });

  it("uses the current modal teardown prop", () => {
    const source = read("pages/Settings/Agents/components/CopyAgentModal.tsx");
    expect(source).toContain("destroyOnHidden");
    expect(source).not.toContain("destroyOnClose");
  });
});
