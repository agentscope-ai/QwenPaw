/**
 * useIconDrag.ts — Transient drag gesture for desktop icons.
 *
 * Same model as window drags: pointermove writes straight to the icon's
 * DOM node (rAF-coalesced) and the persisted icon store is written ONCE
 * when the gesture ends. pointercancel / lostpointercapture finalize the
 * same way, so system-cancelled gestures never leave the DOM and the
 * store out of sync.
 *
 * Pointer capture is deferred until the pointer leaves a small click
 * slop, so plain clicks / double-clicks on the icon keep working.
 */
import { useCallback, useRef } from "react";

interface IconDragState {
  id: string;
  el: HTMLElement;
  dx: number;
  dy: number;
  sx: number;
  sy: number;
  originX: number;
  originY: number;
  moved: boolean;
  pending: { x: number; y: number } | null;
  raf: number | null;
}

export interface IconDragHandlers {
  onPointerDown: (e: React.PointerEvent) => void;
  onPointerMove: (e: React.PointerEvent) => void;
  onPointerUp: (e: React.PointerEvent) => void;
  onPointerCancel: (e: React.PointerEvent) => void;
  onLostPointerCapture: (e: React.PointerEvent) => void;
}

export interface IconDragEnd {
  (id: string, event: React.PointerEvent, moved: boolean): boolean | void;
}

/** Pixels of movement tolerated before a press becomes a drag. */
const CLICK_SLOP = 3;

function elementAtPoint(x: number, y: number): Element | null {
  return document.elementFromPoint?.(x, y) ?? null;
}

export function useIconDrag(
  setPosition: (id: string, x: number, y: number) => void,
  minY: number,
  onDragEnd?: IconDragEnd,
): (id: string, pos: { x: number; y: number }) => IconDragHandlers {
  const dragRef = useRef<IconDragState | null>(null);

  // Finalize: commit the last transient position once, clear all refs.
  // Bound to pointerup, pointercancel AND lostpointercapture; safe to run
  // multiple times per gesture (the capture-release cascade re-enters it).
  const end = useCallback(
    (e: React.PointerEvent) => {
      const d = dragRef.current;
      dragRef.current = null;
      if (d) {
        if (d.raf !== null) cancelAnimationFrame(d.raf);
        window.dispatchEvent(
          new CustomEvent("os-dock-dragover", { detail: { active: false } }),
        );
        const handled =
          e.type === "pointerup" && onDragEnd?.(d.id, e, d.moved) === true;
        if (handled) {
          d.el.style.left = `${d.originX}px`;
          d.el.style.top = `${d.originY}px`;
        }
        if (!handled && d.moved && d.pending) {
          setPosition(d.id, d.pending.x, d.pending.y);
        }
      }
      try {
        (e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId);
      } catch {
        /* capture already released */
      }
    },
    [onDragEnd, setPosition],
  );

  return useCallback(
    (id, pos) => ({
      onPointerDown: (e) => {
        if ((e.target as HTMLElement).closest("button")) return;
        // No pointer capture here: capturing on pointerdown would redirect
        // the compatibility click/dblclick events to this wrapper, so the
        // icon's onDoubleClick (open app) would never fire. Capture is
        // deferred until a real drag starts.
        dragRef.current = {
          id,
          el: e.currentTarget as HTMLElement,
          dx: e.clientX - pos.x,
          dy: e.clientY - pos.y,
          sx: e.clientX,
          sy: e.clientY,
          originX: pos.x,
          originY: pos.y,
          moved: false,
          pending: null,
          raf: null,
        };
      },
      onPointerMove: (e) => {
        const d = dragRef.current;
        if (!d || d.id !== id) return;
        if (!d.moved) {
          // Still within the click slop — leave clicks untouched.
          if (
            Math.abs(e.clientX - d.sx) <= CLICK_SLOP &&
            Math.abs(e.clientY - d.sy) <= CLICK_SLOP
          ) {
            return;
          }
          d.moved = true;
          (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        }
        // Transient: DOM only (one write per frame) — the persisted store
        // is untouched until the gesture ends.
        d.pending = {
          x: Math.max(0, e.clientX - d.dx),
          y: Math.max(minY, e.clientY - d.dy),
        };
        const overDock = elementAtPoint(e.clientX, e.clientY)?.closest(
          "[data-os-dock-dropzone]",
        );
        window.dispatchEvent(
          new CustomEvent("os-dock-dragover", {
            detail: { active: Boolean(overDock) },
          }),
        );
        if (d.raf === null) {
          d.raf = requestAnimationFrame(() => {
            d.raf = null;
            if (d.pending) {
              d.el.style.left = `${d.pending.x}px`;
              d.el.style.top = `${d.pending.y}px`;
            }
          });
        }
      },
      onPointerUp: end,
      onPointerCancel: end,
      onLostPointerCapture: end,
    }),
    [end, minY],
  );
}
