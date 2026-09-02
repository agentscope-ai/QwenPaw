/**
 * Geometry for a reverse (column-reverse) chat transcript.
 *
 * The SDK scroller uses flex-direction: column-reverse: scrollTop === 0 is
 * the newest edge (visual bottom) and scrollTop goes negative toward older
 * messages. Offsets are measured from that newest edge so prepended older
 * rows only grow the far end of the list.
 */

export const DEFAULT_ESTIMATED_ROW_HEIGHT = 96;
export const DEFAULT_ROW_GAP = 24;
export const DEFAULT_OVERSCAN_PX = 800;
export const DEFAULT_OVERSCAN_COUNT = 3;
export const NEAR_OLDEST_PX = 80;
export const AT_NEWEST_PX = 2;

export function itemKey(
  item: { id?: string; key?: string | number },
  index: number,
): string {
  if (typeof item.id === "string" && item.id.length > 0) return item.id;
  if (item.key !== undefined && item.key !== null) return String(item.key);
  return `idx-${index}`;
}

export function accumulateOffsets(
  keys: readonly string[],
  heights: ReadonlyMap<string, number>,
  estimatedHeight: number,
  gap: number,
): { offsets: number[]; sizes: number[]; total: number } {
  const offsets: number[] = [];
  const sizes: number[] = [];
  let cursor = 0;
  for (let index = 0; index < keys.length; index += 1) {
    offsets.push(cursor);
    const size = heights.get(keys[index]) ?? estimatedHeight;
    sizes.push(size);
    cursor += size;
    if (index < keys.length - 1) cursor += gap;
  }
  return { offsets, sizes, total: cursor };
}

export function reverseViewWindow(
  scrollTop: number,
  clientHeight: number,
  overscanPx: number,
): { viewStart: number; viewEnd: number } {
  const viewStart = Math.max(0, -scrollTop);
  const viewport = Math.max(0, clientHeight);
  return {
    viewStart: Math.max(0, viewStart - overscanPx),
    viewEnd: viewStart + viewport + overscanPx,
  };
}

export function getVisibleIndexRange(
  offsets: readonly number[],
  sizes: readonly number[],
  viewStart: number,
  viewEnd: number,
): { start: number; end: number } {
  if (offsets.length === 0) return { start: 0, end: -1 };

  let start = 0;
  while (start < offsets.length && offsets[start] + sizes[start] < viewStart) {
    start += 1;
  }
  if (start >= offsets.length) start = offsets.length - 1;

  let end = start;
  while (end < offsets.length - 1 && offsets[end] + sizes[end] < viewEnd) {
    end += 1;
  }
  return { start, end };
}

export function expandIndexRange(
  start: number,
  end: number,
  length: number,
  extra: number,
): { start: number; end: number } {
  if (length === 0 || end < start) return { start: 0, end: -1 };
  return {
    start: Math.max(0, start - extra),
    end: Math.min(length - 1, end + extra),
  };
}

export function computeSpacers(
  start: number,
  end: number,
  offsets: readonly number[],
  sizes: readonly number[],
  total: number,
): { startSpacer: number; endSpacer: number } {
  if (offsets.length === 0 || end < start) {
    return { startSpacer: 0, endSpacer: total };
  }
  const startSpacer = offsets[start] ?? 0;
  const lastEdge = (offsets[end] ?? 0) + (sizes[end] ?? 0);
  return {
    startSpacer,
    endSpacer: Math.max(0, total - lastEdge),
  };
}

export function isAtNewestEdge(
  scrollTop: number,
  thresholdPx = AT_NEWEST_PX,
): boolean {
  return scrollTop >= -thresholdPx;
}

export function isNearOldestEdge(
  scrollTop: number,
  scrollHeight: number,
  clientHeight: number,
  thresholdPx = NEAR_OLDEST_PX,
): boolean {
  const maxDistance = Math.max(scrollHeight - clientHeight, 0);
  if (maxDistance <= 0) return false;
  const distanceFromNewest = Math.abs(Math.min(scrollTop, 0));
  return maxDistance - distanceFromNewest <= thresholdPx;
}

export function scrollTopForIndex(
  index: number,
  offsets: readonly number[],
  sizes: readonly number[],
  clientHeight: number,
  align: "newest" | "oldest" = "oldest",
): number {
  if (index < 0 || index >= offsets.length) return 0;
  if (align === "newest") return -offsets[index];
  const viewStart = Math.max(
    0,
    offsets[index] + sizes[index] - Math.max(clientHeight, 0),
  );
  return -viewStart;
}

/**
 * How far the newest edge grew: new rows inserted before the previous
 * newest id, or that live row getting taller (streaming / cards).
 */
export function newestEdgeGrowthPx(
  previousNewestKey: string | null,
  keys: readonly string[],
  offsets: readonly number[],
  previousNewestSize: number,
  nextNewestSize: number,
): number {
  if (!previousNewestKey || keys.length === 0) return 0;
  const index = keys.indexOf(previousNewestKey);
  if (index > 0) return Math.max(0, offsets[index] ?? 0);
  if (index === 0) return nextNewestSize - previousNewestSize;
  return 0;
}

/**
 * Reverse lists pin scrollTop === 0 at the newest edge. If the user has
 * scrolled toward older messages, growing that newest edge must move
 * scrollTop by the same amount so the anchor does not jump.
 */
export function preserveReverseAnchorScrollTop(
  scrollTop: number,
  atNewest: boolean,
  growthPx: number,
): number {
  if (atNewest) return 0;
  return scrollTop - growthPx;
}

export interface ReverseScrollAnchor {
  key: string;
  offsetInItem: number;
}

/** Row that sits at `viewStart` pixels from the newest edge. */
export function reverseAnchorAt(
  viewStart: number,
  keys: readonly string[],
  offsets: readonly number[],
  sizes: readonly number[],
): ReverseScrollAnchor | null {
  if (keys.length === 0 || offsets.length === 0) return null;
  let index = 0;
  while (index < keys.length && offsets[index] + sizes[index] <= viewStart) {
    index += 1;
  }
  if (index >= keys.length) index = keys.length - 1;
  return {
    key: keys[index],
    offsetInItem: viewStart - (offsets[index] ?? 0),
  };
}

export function scrollTopForReverseAnchor(
  anchor: ReverseScrollAnchor,
  keys: readonly string[],
  offsets: readonly number[],
): number | null {
  const index = keys.indexOf(anchor.key);
  if (index < 0) return null;
  return -((offsets[index] ?? 0) + anchor.offsetInItem);
}
