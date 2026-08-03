/** Segmented pill tabs shared by the home and project headers. */

export const SEGMENTED_TRACK_CLASS =
  "flex items-center rounded-full bg-[rgba(43,27,0,0.04)] p-1";

export function segmentedItemClass(active: boolean): string {
  const base =
    "flex cursor-pointer items-center gap-1 rounded-full border px-3 py-1 text-sm font-medium leading-6 transition-colors";
  return active
    ? `${base} border-[#FFD7AC] bg-[#FFF3E6] text-[#332F2E]`
    : `${base} border-transparent text-[#656563] hover:text-[var(--color-text-primary)]`;
}
