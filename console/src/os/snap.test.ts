import { describe, it, expect } from "vitest";
import { computeSnapRect } from "./snap";
import { MENUBAR_H } from "./useOsStyles";

describe("computeSnapRect", () => {
  it("left half fills the left side below the menu bar", () => {
    const r = computeSnapRect("left", 1000, 800);
    expect(r).toEqual({ x: 0, y: MENUBAR_H, w: 500, h: 800 - MENUBAR_H });
  });

  it("right half is offset by its width", () => {
    const r = computeSnapRect("right", 1000, 800);
    expect(r).toEqual({ x: 500, y: MENUBAR_H, w: 500, h: 800 - MENUBAR_H });
  });

  it("maximize returns the full working area", () => {
    const r = computeSnapRect("maximize", 1000, 800);
    expect(r).toEqual({ x: 0, y: MENUBAR_H, w: 1000, h: 800 - MENUBAR_H });
  });

  it("floors odd widths so halves stay integral", () => {
    const r = computeSnapRect("right", 999, 800);
    expect(r.w).toBe(499);
    expect(r.x).toBe(999 - 499);
  });
});
