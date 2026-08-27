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
