export const FIXED_SIDEBAR_ITEM_IDS = [
  "core.inbox",
  "core.marketplace",
] as const;

export function isFixedSidebarItemId(itemId: string): boolean {
  return FIXED_SIDEBAR_ITEM_IDS.some((fixedId) => fixedId === itemId);
}
