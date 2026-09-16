import type { MenuItem } from "../plugins/registry/types";
import { can, type PlatformMode, type PlatformRole } from "./capabilities";

type MenuTreeItem = MenuItem & { __children?: MenuItem[] };

export function filterMenuByCapabilities(
  items: MenuItem[],
  mode: PlatformMode,
  role: PlatformRole | null,
): MenuItem[] {
  if (mode === "legacy" || role === "admin") return items;

  return items.flatMap((item) => {
    if (item.capability && !can(mode, role, item.capability)) return [];
    const treeItem = item as MenuTreeItem;
    if (!treeItem.__children) return [item];
    const children = filterMenuByCapabilities(
      treeItem.__children,
      mode,
      role,
    );
    if (children.length === 0 && treeItem.isGroup) return [];
    if (children === treeItem.__children) return [item];
    return [{ ...treeItem, __children: children }];
  });
}
