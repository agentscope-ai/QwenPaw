import type { FlatMenuEntry } from "./adapter";
import type { MenuItem } from "../../plugins/registry/types";

export interface SidebarEntryGroups {
  work: FlatMenuEntry[];
  global: FlatMenuEntry[];
  plugins: FlatMenuEntry[];
}

export const SIDEBAR_DIRECT_ENTRY_LIMIT = 5;

export interface SidebarEntryDisplayGroups {
  direct: FlatMenuEntry[];
  overflow: FlatMenuEntry[];
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
      ? item.id === "core.inbox" || focusItemIds.has(item.id)
      : !hiddenPluginItemIds.has(item.id);

  const walk = (candidates: MenuItem[]) => {
    for (const rawItem of candidates) {
      const item = rawItem as MenuItemWithChildren;
      if (item.__children?.length) {
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
        (entry) => entry.key.startsWith("core.") && entry.key !== "core.inbox",
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

export function splitSidebarEntriesForDisplay(
  entries: FlatMenuEntry[],
  limit = SIDEBAR_DIRECT_ENTRY_LIMIT,
): SidebarEntryDisplayGroups {
  const safeLimit = Math.max(0, limit);
  return {
    direct: entries.slice(0, safeLimit),
    overflow: entries.slice(safeLimit),
  };
}
