/**
 * useEdgeReveal.ts — Tracks whether the pointer is near the top or bottom
 * screen edge, so the menu bar / Dock / Spaces panel can auto-reveal.
 *
 * `resolveEdges` is a pure resolver (unit-testable without the DOM); the hook
 * wires it to a rAF-throttled global pointermove listener with hysteresis:
 * a wider "band" keeps an edge revealed once it has been triggered.
 */
import { useEffect, useRef, useState } from "react";

export interface EdgeState {
  topHot: boolean;
  bottomHot: boolean;
}

export interface EdgeOptions {
  threshold?: number;
  topBand?: number;
  bottomBand?: number;
}

interface ResolvedOpts {
  threshold: number;
  topBand: number;
  bottomBand: number;
}

/** Pure edge resolver. `prev` enables hysteresis (stay open within the band). */
export function resolveEdges(
  y: number,
  innerHeight: number,
  prev: EdgeState,
  opts: ResolvedOpts,
): EdgeState {
  const { threshold, topBand, bottomBand } = opts;
  const topHot = prev.topHot ? y <= topBand : y <= threshold;
  const bottomHot = prev.bottomHot
    ? y >= innerHeight - bottomBand
    : y >= innerHeight - threshold;
  return { topHot, bottomHot };
}

export function useEdgeReveal(options: EdgeOptions = {}): EdgeState {
  const threshold = options.threshold ?? 6;
  const topBand = options.topBand ?? 120;
  const bottomBand = options.bottomBand ?? 96;

  const [edges, setEdges] = useState<EdgeState>({
    topHot: false,
    bottomHot: false,
  });
  const stateRef = useRef(edges);
  stateRef.current = edges;
  const rafRef = useRef(0);

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      if (rafRef.current) return;
      rafRef.current = requestAnimationFrame(() => {
        rafRef.current = 0;
        const next = resolveEdges(
          e.clientY,
          window.innerHeight,
          stateRef.current,
          { threshold, topBand, bottomBand },
        );
        if (
          next.topHot !== stateRef.current.topHot ||
          next.bottomHot !== stateRef.current.bottomHot
        ) {
          setEdges(next);
        }
      });
    };
    window.addEventListener("pointermove", onMove);
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
    };
  }, [threshold, topBand, bottomBand]);

  return edges;
}
