export interface AnchorRect {
  height: number;
  width: number;
  x: number;
  y: number;
}

export interface MenuPlacement {
  above: boolean;
  arrowLeft: number;
  left: number;
  top: number;
}

export function placeAnchoredMenu({
  anchor,
  bottomInset,
  gap,
  margin,
  menuHeight,
  menuWidth,
  topInset,
  viewportHeight,
  viewportWidth,
}: {
  anchor: AnchorRect;
  bottomInset: number;
  gap: number;
  margin: number;
  menuHeight: number;
  menuWidth: number;
  topInset: number;
  viewportHeight: number;
  viewportWidth: number;
}): MenuPlacement {
  const minLeft = margin;
  const maxLeft = Math.max(minLeft, viewportWidth - menuWidth - margin);
  const anchorCenter = anchor.x + anchor.width / 2;
  const left = clamp(anchorCenter - menuWidth / 2, minLeft, maxLeft);
  const minTop = topInset + margin;
  const maxTop = Math.max(
    minTop,
    viewportHeight - bottomInset - margin - menuHeight,
  );
  const spaceAbove = anchor.y - gap - minTop;
  const spaceBelow = maxTop - (anchor.y + anchor.height + gap);
  const above = spaceAbove >= menuHeight || spaceAbove >= spaceBelow;
  const desiredTop = above
    ? anchor.y - gap - menuHeight
    : anchor.y + anchor.height + gap;
  const arrowLeft = clamp(anchorCenter - left - 6, 14, menuWidth - 26);

  return {
    above,
    arrowLeft,
    left,
    top: clamp(desiredTop, minTop, maxTop),
  };
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}
