import { describe, it, expect, vi } from "vitest";
import type { BuiltinUpdateNotice } from "@/api/types";
import { getBuiltinNoticeLines } from "./builtinNotice";

const t = vi.fn((key: string, params?: Record<string, unknown>) =>
  params ? `${key}:${(params as { names?: string }).names ?? ""}` : key,
);

function notice(overrides: Partial<BuiltinUpdateNotice>): BuiltinUpdateNotice {
  return {
    fingerprint: "fp",
    has_updates: true,
    total_changes: 0,
    actionable_skill_names: [],
    added: [],
    missing: [],
    updated: [],
    removed: [],
    ...overrides,
  } as BuiltinUpdateNotice;
}

describe("getBuiltinNoticeLines", () => {
  it("returns [] when notice is null", () => {
    t.mockClear();
    expect(getBuiltinNoticeLines(null, t as any)).toEqual([]);
    expect(t).not.toHaveBeenCalled();
  });

  it("returns [] when has_updates is not true", () => {
    t.mockClear();
    expect(
      getBuiltinNoticeLines(notice({ has_updates: false }), t as any),
    ).toEqual([]);
    expect(t).not.toHaveBeenCalled();
  });

  it("emits one line for the added category only", () => {
    t.mockClear();
    const n = notice({ added: [{ name: "skillA" }, { name: "skillB" }] });
    const lines = getBuiltinNoticeLines(n, t as any);
    expect(lines).toEqual(["skillPool.builtinNoticeLineAdded:skillA, skillB"]);
    expect(t).toHaveBeenCalledWith("skillPool.builtinNoticeLineAdded", {
      names: "skillA, skillB",
    });
  });

  it("emits one line per non-empty category (added + removed)", () => {
    t.mockClear();
    const n = notice({
      added: [{ name: "skillA" }],
      removed: [{ name: "skillZ" }],
    });
    const lines = getBuiltinNoticeLines(n, t as any);
    expect(lines).toEqual([
      "skillPool.builtinNoticeLineAdded:skillA",
      "skillPool.builtinNoticeLineRemoved:skillZ",
    ]);
  });

  it("returns [] when every category array is empty (has_updates=true but no changes listed)", () => {
    t.mockClear();
    const n = notice({
      added: [],
      missing: [],
      updated: [],
      removed: [],
    });
    expect(getBuiltinNoticeLines(n, t as any)).toEqual([]);
    expect(t).not.toHaveBeenCalled();
  });

  it("filters out empty/whitespace names so no line is emitted for them", () => {
    t.mockClear();
    const n = notice({
      added: [{ name: "  " }, { name: "" }],
      updated: [{ name: "real" }],
    });
    const lines = getBuiltinNoticeLines(n, t as any);
    expect(lines).toEqual(["skillPool.builtinNoticeLineUpdated:real"]);
  });
});
