import { describe, expect, it } from "vitest";
import { usagePanelPosition } from "./sidebarPlacement";

describe("usage panel anchoring", () => {
  const size = { width: 540, height: 464 };
  const viewport = { width: 1720, height: 828 };
  it("uses the current trigger after dragging and keeps the panel visible", () => {
    const docked = usagePanelPosition(
      { left: 15, right: 265, bottom: 752 },
      size,
      viewport,
    );
    const floating = usagePanelPosition(
      { left: 563, right: 813, bottom: 655 },
      size,
      viewport,
    );
    expect(docked).toEqual({ left: 277, top: 288 });
    expect(floating).toEqual({ left: 825, top: 191 });
    expect(floating.top + size.height).toBeLessThan(viewport.height);
  });
  it("flips left near the right edge, including a small desktop window", () => {
    const position = usagePanelPosition(
      { left: 680, right: 930, bottom: 580 },
      size,
      { width: 960, height: 600 },
    );
    expect(position).toEqual({ left: 128, top: 116 });
  });
  it("clamps the panel inside an OS window's local bounds", () => {
    expect(
      usagePanelPosition({ left: 20, right: 270, bottom: 300 }, size, {
        width: 700,
        height: 600,
      }),
    ).toEqual({ left: 12, top: 12 });
  });
});
