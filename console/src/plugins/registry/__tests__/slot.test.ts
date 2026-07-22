/**
 * slot.test.ts — SlotRegistry pure behaviour (no React render).
 */
import { describe, it, expect, beforeEach } from "vitest";
import { slotRegistry } from "../store";
import { auditStore } from "../audit";

beforeEach(() => {
  slotRegistry.__resetForTests();
  auditStore.clear();
});

describe("slotRegistry.fill", () => {
  it("appends fills in registration order when no order opts", () => {
    slotRegistry.fill("p1", "x", () => null, { id: "a" });
    slotRegistry.fill("p2", "x", () => null, { id: "b" });
    expect(slotRegistry.snapshot("x").map((e) => e.opts.id)).toEqual([
      "a",
      "b",
    ]);
  });

  it("sorts by order ascending", () => {
    slotRegistry.fill("p1", "x", () => null, { id: "a", order: 30 });
    slotRegistry.fill("p2", "x", () => null, { id: "b", order: 10 });
    slotRegistry.fill("p3", "x", () => null, { id: "c", order: 20 });
    expect(slotRegistry.snapshot("x").map((e) => e.opts.id)).toEqual([
      "b",
      "c",
      "a",
    ]);
  });

  it("respects before/after constraints", () => {
    slotRegistry.fill("p1", "x", () => null, { id: "a" });
    slotRegistry.fill("p2", "x", () => null, { id: "b" });
    slotRegistry.fill("p3", "x", () => null, { id: "z", before: "a" });
    const ids = slotRegistry.snapshot("x").map((e) => e.opts.id);
    expect(ids.indexOf("z")).toBeLessThan(ids.indexOf("a"));
  });

  it("filters by visible()", () => {
    slotRegistry.fill("p1", "x", () => null, {
      id: "shown",
      visible: () => true,
    });
    slotRegistry.fill("p2", "x", () => null, {
      id: "hidden",
      visible: () => false,
    });
    expect(slotRegistry.snapshot("x").map((e) => e.opts.id)).toEqual(["shown"]);
  });

  it("dispose removes only the targeted fill", () => {
    slotRegistry.fill("p1", "x", () => null, { id: "a" });
    const d = slotRegistry.fill("p2", "x", () => null, { id: "b" });
    slotRegistry.fill("p3", "x", () => null, { id: "c" });
    d.dispose();
    expect(slotRegistry.snapshot("x").map((e) => e.opts.id)).toEqual([
      "a",
      "c",
    ]);
  });
});

describe("slotRegistry.replace", () => {
  it("replace wins over fills", () => {
    slotRegistry.fill("p1", "x", () => null, { id: "fill1" });
    slotRegistry.fill("p2", "x", () => null, { id: "fill2" });
    slotRegistry.replace("p3", "x", () => null, { id: "rep" });
    const snap = slotRegistry.snapshot("x");
    expect(snap).toHaveLength(1);
    expect(snap[0].kind).toBe("replace");
    expect(snap[0].opts.id).toBe("rep");
  });

  it("last replace wins among multiple replacers", () => {
    slotRegistry.replace("p1", "x", () => null, { id: "r1" });
    slotRegistry.replace("p2", "x", () => null, { id: "r2" });
    const snap = slotRegistry.snapshot("x");
    expect(snap).toHaveLength(1);
    expect(snap[0].opts.id).toBe("r2");
  });

  it("disposing the replace reveals fills again", () => {
    slotRegistry.fill("p1", "x", () => null, { id: "f" });
    const d = slotRegistry.replace("p2", "x", () => null, { id: "r" });
    d.dispose();
    const snap = slotRegistry.snapshot("x");
    expect(snap.map((e) => e.opts.id)).toEqual(["f"]);
  });
});

describe("slotRegistry audit", () => {
  it("records replace + fill kinds", () => {
    slotRegistry.fill("p1", "x", () => null, {});
    slotRegistry.replace("p2", "x", () => null, {});
    const kinds = auditStore.overrides().map((r) => r.kind);
    expect(kinds).toContain("slot.fill");
    expect(kinds).toContain("slot.replace");
  });
});

describe("slotRegistry.snapshotAll", () => {
  it("lists all registered slots across names", () => {
    slotRegistry.fill("p1", "a", () => null, { id: "1" });
    slotRegistry.replace("p2", "b", () => null, { id: "2" });
    const all = slotRegistry.snapshotAll();
    expect(all.map((s) => `${s.name}:${s.id}`).sort()).toEqual(["a:1", "b:2"]);
  });
});
