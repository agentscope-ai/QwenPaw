import type { FlatMenuEntry } from "./adapter";
import type { MenuItem } from "../../plugins/registry/types";
import { isFixedSidebarItemId } from "../../constants/sidebarItems";

export interface SidebarEntryGroups {
  work: FlatMenuEntry[];
  global: FlatMenuEntry[];
  plugins: FlatMenuEntry[];
}

function unique(entries: FlatMenuEntry[]): FlatMenuEntry[] {
  return [...new Map(entries.map((entry) => [entry.key, entry])).values()];
}

type MenuItemWithChildren = MenuItem & { __children?: MenuItem[] };

/**
 * Return selected menu leaves in registry order. Groups are navigation-only
 * containers, so their depth and IDs never need to enter user preferences.
 */
export function filterSidebarMenuItems(
  items: MenuItem[],
  focusItemIds: ReadonlySet<string>,
  hiddenPluginItemIds: ReadonlySet<string>,
): MenuItem[] {
  const result: MenuItem[] = [];
  const isVisible = (item: MenuItem) =>
    item.id.startsWith("core.")
      ? isFixedSidebarItemId(item.id) || focusItemIds.has(item.id)
      : !hiddenPluginItemIds.has(item.id);

  const walk = (candidates: MenuItem[]) => {
    for (const rawItem of candidates) {
      const item = rawItem as MenuItemWithChildren;
      if (Array.isArray(item.__children)) {
        walk(item.__children);
      } else if (isVisible(item)) {
        result.push(item);
      }
    }
  };

  walk(items);
  return result;
}

export function partitionSidebarEntries(
  agentEntries: FlatMenuEntry[],
  settingsEntries: FlatMenuEntry[],
): SidebarEntryGroups {
  return {
    work: unique(
      agentEntries.filter(
        (entry) =>
          entry.key.startsWith("core.") && !isFixedSidebarItemId(entry.key),
      ),
    ),
    global: unique(
      settingsEntries.filter((entry) => entry.key.startsWith("core.")),
    ),
    plugins: unique(
      [...agentEntries, ...settingsEntries].filter(
        (entry) => !entry.key.startsWith("core."),
      ),
    ),
  };
}

/**
 * Put configured shortcuts first and preserve registry order for the rest.
 */
export function orderSidebarEntries(
  entries: FlatMenuEntry[],
  preferredItemIds: readonly string[],
): FlatMenuEntry[] {
  const preferredOrder = new Map(
    preferredItemIds.map((itemId, index) => [itemId, index]),
  );

  return [...entries].sort((left, right) => {
    const leftOrder = preferredOrder.get(left.key);
    const rightOrder = preferredOrder.get(right.key);

    if (leftOrder === undefined && rightOrder === undefined) return 0;
    if (leftOrder === undefined) return 1;
    if (rightOrder === undefined) return -1;
    return leftOrder - rightOrder;
  });
}
