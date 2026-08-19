/**
 * snap.ts — Pure geometry helpers for window edge-snapping.
 *
 * Half-screen and maximize rects are computed against the working area
 * (viewport minus the menu bar). The Dock floats over windows (matching the
 * existing maximize behaviour), so it is not subtracted here.
 */
import type { OsRect } from "./osWindowStore";
import { MENUBAR_H } from "./useOsStyles";

export type SnapZone = "left" | "right" | "maximize";

export function computeSnapRect(
  zone: SnapZone,
  vw: number,
  vh: number,
): OsRect {
  const y = MENUBAR_H;
  const h = vh - MENUBAR_H;
  if (zone === "maximize") {
    return { x: 0, y, w: vw, h };
  }
  const w = Math.floor(vw / 2);
  if (zone === "left") {
    return { x: 0, y, w, h };
  }
  return { x: vw - w, y, w, h };
}
