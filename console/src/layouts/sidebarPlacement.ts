const MARGIN = 12;

export function constrainSidebar(
  position: { x: number; y: number },
  size: { width: number; height: number },
  viewport: { width: number; height: number },
) {
  return {
    x: Math.max(
      MARGIN,
      Math.min(position.x, viewport.width - size.width - MARGIN),
    ),
    y: Math.max(
      MARGIN,
      Math.min(position.y, viewport.height - size.height - MARGIN),
    ),
  };
}

export function usagePanelPosition(
  source: Pick<DOMRect, "left" | "right" | "bottom">,
  size: { width: number; height: number },
  viewport: { width: number; height: number },
) {
  const left =
    source.right + size.width + 24 <= viewport.width
      ? source.right + 12
      : source.left - size.width - 12;
  return {
    left: Math.max(12, Math.min(left, viewport.width - size.width - 12)),
    top: Math.max(
      12,
      Math.min(source.bottom - size.height, viewport.height - size.height - 12),
    ),
  };
}
