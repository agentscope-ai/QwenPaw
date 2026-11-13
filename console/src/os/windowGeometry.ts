/**
 * windowGeometry.ts — Pure viewport-clamping helpers for OS windows.
 *
 * Platform-agnostic geometry rules shared by open(), the persistence
 * migration and post-hydration/resize re-clamping, so a window restored
 * after a DPI change, monitor switch or viewport shrink always keeps its
 * title bar below the menu bar and its full height inside the viewport
 * whenever it fits.
 */
import type { OsRect } from "./osWindowStore";
import { MENUBAR_H } from "./useOsStyles";

/** Optional per-app minimum size (from the app manifest). */
export interface SizeLimits {
  minW?: number;
  minH?: number;
}

/** Horizontal strip of the title bar that must stay reachable. */
const GRAB_X = 80;
/** Absolute size floors for tiny viewports. */
const FLOOR_W = 360;
const FLOOR_H = 260;
/** Breathing room the desktop keeps around a window's max size. */
const PAD_W = 40;
const PAD_H = 140;

/** Keep a window fully inside the viewport bottom when its height fits. */
export function clampWindowY(y: number, h: number, vh: number): number {
  const maxY = Math.max(MENUBAR_H, vh - h);
  return Math.min(Math.max(y, MENUBAR_H), maxY);
}

/**
 * Clamp a window rect to the given viewport work area.
 *
 * Size: at least the app minimum, but never beyond the work area (the
 * work area wins when the two conflict, e.g. on very small screens).
 * Position: the title bar stays horizontally grabbable, while the full
 * height stays inside the viewport whenever it fits.
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
  const y = clampWindowY(rect.y, h, vh);
  return { x, y, w, h };
}
