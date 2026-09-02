/**
 * Security-scan error handling: parses scan failures embedded in error
 * messages and surfaces blocked-skill findings via modals. Defects here
 * hide security verdicts from the user.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

const modalError = vi.fn();
const modalWarning = vi.fn();

vi.mock("@agentscope-ai/design", () => ({
  Modal: {
    error: (...args: unknown[]) => modalError(...args),
    warning: (...args: unknown[]) => modalWarning(...args),
  },
}));

import {
  tryParseScanError,
  handleScanError,
  checkScanWarnings,
} from "./scanError";

const t = ((key: string) => key) as any;

beforeEach(() => {
  modalError.mockClear();
  modalWarning.mockClear();
});

describe("tryParseScanError", () => {
  it("returns null for non-Error values", () => {
    expect(tryParseScanError("plain string")).toBeNull();
    expect(tryParseScanError(null)).toBeNull();
  });

  it("returns null when the message has no JSON payload", () => {
    expect(tryParseScanError(new Error("network down"))).toBeNull();
  });

  it("returns null when the JSON is not a scan failure", () => {
    const error = new Error('failed {"type": "other", "detail": "x"}');
    expect(tryParseScanError(error)).toBeNull();
  });

  it("parses a security_scan_failed payload", () => {
    const payload = {
      type: "security_scan_failed",
      findings: [{ title: "eval usage", file_path: "index.ts" }],
    };
    const error = new Error(`Install failed ${JSON.stringify(payload)}`);
    expect(tryParseScanError(error)).toEqual(payload);
  });

  it("returns null when the embedded JSON is malformed", () => {
    const error = new Error("failed {broken json");
    expect(tryParseScanError(error)).toBeNull();
  });
});

describe("handleScanError", () => {
  it("shows the error modal and reports handled for a scan failure", () => {
    const payload = { type: "security_scan_failed", findings: [] };
    const error = new Error(`boom ${JSON.stringify(payload)}`);
    expect(handleScanError(error, t)).toBe(true);
    expect(modalError).toHaveBeenCalledTimes(1);
    expect(modalError.mock.calls[0][0].title).toBe(
      "security.skillScanner.scanError.title",
    );
  });

  it("returns false and shows nothing for a non-scan error", () => {
    expect(handleScanError(new Error("generic failure"), t)).toBe(false);
    expect(modalError).not.toHaveBeenCalled();
  });
});

describe("checkScanWarnings", () => {
  const finding = { title: "dangerous call", file_path: "a.ts" };
  const warnedAlert = {
    skill_name: "my-skill",
    action: "warned",
    findings: [finding],
  };

  const noAlerts = () => Promise.resolve([]);
  const defaultCfg = () => Promise.resolve({ whitelist: [] } as any);

  it("does nothing when there are no alerts", async () => {
    await checkScanWarnings("my-skill", noAlerts, defaultCfg, t);
    expect(modalWarning).not.toHaveBeenCalled();
  });

  it("does nothing when the skill is whitelisted", async () => {
    const alerts = () => Promise.resolve([warnedAlert] as any);
    const cfg = () =>
      Promise.resolve({ whitelist: [{ skill_name: "my-skill" }] } as any);
    await checkScanWarnings("my-skill", alerts, cfg, t);
    expect(modalWarning).not.toHaveBeenCalled();
  });

  it("shows a warning modal for the latest warned alert of the skill", async () => {
    const alerts = () => Promise.resolve([warnedAlert] as any);
    await checkScanWarnings("my-skill", alerts, defaultCfg, t);
    expect(modalWarning).toHaveBeenCalledTimes(1);
    expect(modalWarning.mock.calls[0][0].title).toBe(
      "security.skillScanner.scanError.title",
    );
  });

  it("ignores alerts for other skills or non-warned actions", async () => {
    const alerts = () =>
      Promise.resolve([
        { skill_name: "other-skill", action: "warned", findings: [] },
        { skill_name: "my-skill", action: "blocked", findings: [] },
      ] as any);
    await checkScanWarnings("my-skill", alerts, defaultCfg, t);
    expect(modalWarning).not.toHaveBeenCalled();
  });

  it("swallows fetch failures without throwing (best-effort)", async () => {
    const failing = () => Promise.reject(new Error("backend down"));
    await expect(
      checkScanWarnings("my-skill", failing, defaultCfg, t),
    ).resolves.toBeUndefined();
    expect(modalWarning).not.toHaveBeenCalled();
  });
});
