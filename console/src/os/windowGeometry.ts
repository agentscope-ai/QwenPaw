/**
 * windowGeometry.ts — Pure viewport-clamping helpers for OS windows.
 *
 * Platform-agnostic geometry rules shared by open(), the persistence
 * migration and post-hydration/resize re-clamping, so a window restored
 * after a DPI change, monitor switch or viewport shrink always keeps its
 * title bar inside the operable work area (viewport minus menu bar, with
 * a grab strip above the Dock).
 */
import type { OsRect } from "./osWindowStore";
import { MENUBAR_H, DOCK_H } from "./useOsStyles";

/** Optional per-app minimum size (from the app manifest). */
export interface SizeLimits {
  minW?: number;
  minH?: number;
}

/** Horizontal strip of the title bar that must stay reachable. */
const GRAB_X = 80;
/** Vertical space kept free above the Dock (matches the drag clamp). */
const GRAB_BOTTOM = DOCK_H + 40;
/** Absolute size floors for tiny viewports. */
const FLOOR_W = 360;
const FLOOR_H = 260;
/** Breathing room the desktop keeps around a window's max size. */
const PAD_W = 40;
const PAD_H = 140;

/**
 * Clamp a window rect to the given viewport work area.
 *
 * Size: at least the app minimum, but never beyond the work area (the
 * work area wins when the two conflict, e.g. on very small screens).
 * Position: the title bar always stays grabbable — x within
 * [0, vw - GRAB_X], y within [MENUBAR_H, vh - GRAB_BOTTOM].
 */
export function clampRectToViewport(
  rect: OsRect,
  limits: SizeLimits,
  vw: number,
  vh: number,
): OsRect {
  const maxW = Math.max(FLOOR_W, vw - PAD_W);
  const maxH = Math.max(FLOOR_H, vh - PAD_H);
  const w = Math.min(Math.max(rect.w, limits.minW ?? 0), maxW);
  const h = Math.min(Math.max(rect.h, limits.minH ?? 0), maxH);
  const x = Math.min(Math.max(rect.x, 0), Math.max(0, vw - GRAB_X));
  const y = Math.min(
    Math.max(rect.y, MENUBAR_H),
    Math.max(MENUBAR_H, vh - GRAB_BOTTOM),
  );
  return { x, y, w, h };
}
