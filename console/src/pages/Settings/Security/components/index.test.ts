/**
 * components/index.ts - the barrel of the Security page component folder.
 *
 * What is pinned here is the public surface the rest of the page depends on:
 * `Security/index.tsx` imports six of these names through the barrel and
 * `ToolGuardTab.tsx` imports two more through it, so a name that silently
 * disappears from the barrel breaks the page rather than one test. The
 * assertions therefore check (a) the exact set of exported names, (b) that
 * every one of them is a component, (c) that each barrel binding is the very
 * same object the sibling module exports (so the barrel cannot quietly
 * re-export something else under a familiar name), and (d) that the barrel
 * exposes no default export, because `export *` never forwards one and a
 * consumer written against named imports would break if that changed.
 *
 * Stub notes, each one measured against the real modules before writing:
 * - No module in this folder is mocked: importing the barrel was measured to
 *   resolve and evaluate all eight siblings without any stub (probe:
 *   BARREL_keys_count=8, every TYPE_*=function, negative control undefined).
 * - The expected name list is written out explicitly instead of being derived
 *   from the barrel itself, otherwise the assertion would agree with whatever
 *   the barrel happens to export and could never fail.
 */
import { describe, expect, it } from "vitest";
import * as barrel from "./index";
import { AllowNoAuthHostsTab } from "./AllowNoAuthHostsTab";
import { FileGuardSection } from "./FileGuardSection";
import { PreviewModal } from "./PreviewModal";
import { RuleModal } from "./RuleModal";
import { RuleTable } from "./RuleTable";
import { ShellEvasionSection } from "./ShellEvasionSection";
import { SkillScannerSection } from "./SkillScannerSection";
import { ToolGuardTab } from "./ToolGuardTab";

const EXPECTED_NAMES = [
  "AllowNoAuthHostsTab",
  "FileGuardSection",
  "PreviewModal",
  "RuleModal",
  "RuleTable",
  "ShellEvasionSection",
  "SkillScannerSection",
  "ToolGuardTab",
];

const bindings: Record<string, unknown> = {
  AllowNoAuthHostsTab,
  FileGuardSection,
  PreviewModal,
  RuleModal,
  RuleTable,
  ShellEvasionSection,
  SkillScannerSection,
  ToolGuardTab,
};

const surface = barrel as unknown as Record<string, unknown>;

describe("Security components barrel", () => {
  it("exports exactly the eight component names the page consumes", () => {
    expect(Object.keys(surface).sort()).toEqual(EXPECTED_NAMES);
  });

  it("exports a component for every expected name", () => {
    for (const name of EXPECTED_NAMES) {
      expect(typeof surface[name], name).toBe("function");
    }
  });

  it.each(EXPECTED_NAMES)(
    "re-exports %s as the same binding its own module exports",
    (name) => {
      expect(surface[name]).toBe(bindings[name]);
    },
  );

  it("exposes no default export", () => {
    expect(surface.default).toBeUndefined();
  });

  it("does not invent names that no sibling module exports", () => {
    // Negative control: a name none of the eight modules declares.
    expect(surface.NonexistentComponent).toBeUndefined();
    expect(surface.ShellEvasion).toBeUndefined();
    expect(surface.RuleTableModal).toBeUndefined();
  });
});
