import { describe, it, expect } from "vitest";
import {
  resolveEdges,
  shouldRevealDock,
  type EdgeState,
} from "./useEdgeReveal";

const OPTS = { threshold: 6, topBand: 120, bottomBand: 96 };
const OFF: EdgeState = { topHot: false, bottomHot: false };

describe("resolveEdges", () => {
  it("arms top when pointer enters the top threshold", () => {
    expect(resolveEdges(3, 800, OFF, OPTS).topHot).toBe(true);
  });

  it("keeps top hot within the revealed band (hysteresis)", () => {
    const prev = { topHot: true, bottomHot: false };
    expect(resolveEdges(90, 800, prev, OPTS).topHot).toBe(true);
  });

  it("releases top once pointer leaves the band", () => {
    const prev = { topHot: true, bottomHot: false };
    expect(resolveEdges(200, 800, prev, OPTS).topHot).toBe(false);
  });

  it("arms bottom near the bottom edge", () => {
    expect(resolveEdges(799, 800, OFF, OPTS).bottomHot).toBe(true);
  });

  it("keeps bottom hot within the bottom band", () => {
    const prev = { topHot: false, bottomHot: true };
    expect(resolveEdges(720, 800, prev, OPTS).bottomHot).toBe(true);
  });

  it("releases bottom once pointer leaves the band", () => {
    const prev = { topHot: false, bottomHot: true };
    expect(resolveEdges(700, 800, prev, OPTS).bottomHot).toBe(false);
  });
});

describe("shouldRevealDock", () => {
  it("keeps the Dock visible without a maximized active window", () => {
    expect(shouldRevealDock(false, false, false)).toBe(true);
  });

  it("hides the Dock for a maximized active window", () => {
    expect(shouldRevealDock(false, true, false)).toBe(false);
  });

  it("reveals the Dock when the pointer reaches the bottom edge", () => {
    expect(shouldRevealDock(false, true, true)).toBe(true);
  });

  it("keeps the Dock visible on mobile", () => {
    expect(shouldRevealDock(true, true, false)).toBe(true);
  });
});
