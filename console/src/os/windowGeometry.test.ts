import { describe, expect, it } from "vitest";
import { clampRectToViewport, clampWindowY } from "./windowGeometry";
import { MENUBAR_H } from "./useOsStyles";

const VW = 1920;
const VH = 1080;

describe("clampRectToViewport", () => {
  it("keeps an in-bounds rect unchanged", () => {
    const rect = { x: 100, y: 80, w: 800, h: 600 };
    expect(clampRectToViewport(rect, {}, VW, VH)).toEqual(rect);
  });

  it("clamps negative coordinates into the work area", () => {
    const out = clampRectToViewport(
      { x: -500, y: -200, w: 800, h: 600 },
      {},
      VW,
      VH,
    );
    expect(out.x).toBe(0);
    expect(out.y).toBe(MENUBAR_H);
  });

  it("pulls off-screen coordinates back so the full height stays visible", () => {
    const out = clampRectToViewport(
      { x: 5000, y: 4000, w: 800, h: 600 },
      {},
      VW,
      VH,
    );
    expect(out.x).toBe(VW - 80);
    expect(out.y).toBe(VH - 600);
  });

  it("shrinks oversized rects to the work area", () => {
    const out = clampRectToViewport(
      { x: 0, y: MENUBAR_H, w: 9000, h: 9000 },
      {},
      VW,
      VH,
    );
    expect(out.w).toBe(VW - 40);
    expect(out.h).toBe(VH - 140);
  });

  it("grows rects up to the app minimum when it fits", () => {
    const out = clampRectToViewport(
      { x: 0, y: MENUBAR_H, w: 400, h: 300 },
      { minW: 960, minH: 560 },
      VW,
      VH,
    );
    expect(out.w).toBe(960);
    expect(out.h).toBe(560);
  });

  it("lets the work area win over the app minimum on small viewports", () => {
    const out = clampRectToViewport(
      { x: 300, y: 300, w: 1200, h: 720 },
      { minW: 960, minH: 560 },
      800,
      500,
    );
    expect(out.w).toBe(760);
    expect(out.h).toBe(360);
    expect(out.x).toBeLessThanOrEqual(800 - 80);
    expect(out.y).toBeGreaterThanOrEqual(MENUBAR_H);
  });
});

describe("clampWindowY", () => {
  it("pins a window taller than the viewport below the menu bar", () => {
    expect(clampWindowY(4000, 1200, 800)).toBe(MENUBAR_H);
  });
});
