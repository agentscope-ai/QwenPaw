/**
 * registry/adapter.tsx — bridge MenuItem (registry shape) → antd Menu items.
 *
 * MenuItem stores neutral data: id, label-as-fn, icon-as-component-or-node,
 * route-id (logical), etc. Sidebar consumes via these helpers to:
 *   - resolve labels/icons into ReactNodes for antd
 *   - look up the URL path from route id (router-driven, no constants table)
 *   - flatten the tree for collapsed mode
 *   - apply Sidebar-local decorations (e.g. inbox unread Badge)
 */
import type { CSSProperties, ReactNode } from "react";
import { createElement, isValidElement } from "react";
import type { MenuProps } from "antd";
import type { MenuItem } from "../../plugins/registry/types";

/** ReactNode + the resolved navigation path for a leaf item (or undefined for groups). */
export interface FlatMenuEntry {
  key: string;
  icon: ReactNode;
  label: ReactNode;
  path: string;
  href?: string;
}

/** Treat MenuItem.icon (Component or Node) as ReactNode with a given size. */
export function renderIcon(icon: MenuItem["icon"], size: number): ReactNode {
  if (icon == null) return null;
  if (isValidElement(icon)) return icon;
  // Component-like: plain function components AND React-internal wrappers
  // (forwardRef / memo / lazy — these are OBJECTS carrying a `$$typeof`
  // symbol, NOT functions; lucide-react + most Spark icons are forwardRef).
  // Anything with `$$typeof` is safe to pass to React.createElement as the
  // first argument.
  if (
    typeof icon === "function" ||
    (typeof icon === "object" &&
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (icon as any).$$typeof !== undefined)
  ) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return createElement(icon as React.ComponentType<any>, { size });
  }
  // Primitive ReactNode (string emoji, number, etc.) — wrap in span at right size.
  const style: CSSProperties = { fontSize: size };
  return <span style={style}>{icon as ReactNode}</span>;
}

export function resolveLabel(label: MenuItem["label"]): ReactNode {
  return typeof label === "function" ? label() : label;
}

export interface RouteRef {
  id: string;
  path: string;
}

/** Look up the path for a route id; falls back to `/<id>` so old behaviour is preserved. */
export function routeIdToPath(
  routeId: string | undefined,
  routes: RouteRef[],
): string | undefined {
  if (!routeId) return undefined;
  const r = routes.find((x) => x.id === routeId);
  return r?.path;
}

interface ToAntdOpts {
  collapsed: boolean;
  iconSize?: number;
  /** Optional Sidebar-local decoration. e.g. wrap inbox label with unread Badge. */
  decorateLabel?: (item: MenuItem, label: ReactNode) => ReactNode;
}

type ItemWithChildren = MenuItem & { __children?: MenuItem[] };

/**
 * Convert a tree of MenuItems (snapshot output) into the antd Menu `items` shape.
 * Top-level items with isGroup or with __children render as expandable groups.
 */
export function toAntdItems(
  items: MenuItem[],
  opts: ToAntdOpts,
): MenuProps["items"] {
  const { collapsed, iconSize = 16, decorateLabel } = opts;
  return items
    .filter((i) => i.visible?.() !== false)
    .map((rawItem) => {
      const i = rawItem as ItemWithChildren;
      const baseLabel = collapsed ? null : resolveLabel(i.label);
      const decorated = decorateLabel ? decorateLabel(i, baseLabel) : baseLabel;
      const node: NonNullable<MenuProps["items"]>[number] = {
        key: i.id,
        label: decorated,
        icon: renderIcon(i.icon, iconSize),
      };
      if (i.__children && i.__children.length > 0) {
        // antd expects `children` on submenu / group items
        const visibleChildren = i.__children.filter(
          (c) => c.visible?.() !== false,
        );
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (node as any).children = toAntdItems(visibleChildren, opts);
      }
      return node;
    });
}

/**
 * Flatten a menu tree into a leaf-only list (for the collapsed icon-nav).
 * Group items are skipped; their children are recursed into.
 */
export function flattenMenu(
  items: MenuItem[],
  routes: RouteRef[],
  iconSize: number,
): FlatMenuEntry[] {
  const out: FlatMenuEntry[] = [];
  const walk = (arr: MenuItem[]) => {
    for (const rawItem of arr) {
      const i = rawItem as ItemWithChildren;
      if (i.visible?.() === false) continue;
      if (i.divider) continue;
      if (i.isGroup || (i.__children && i.__children.length > 0)) {
        walk(i.__children ?? []);
        continue;
      }
      const path = routeIdToPath(i.route, routes);
      if (!path && !i.href) continue;
      out.push({
        key: i.id,
        icon: renderIcon(i.icon, iconSize),
        label: resolveLabel(i.label),
        path: path ?? "",
        href: i.href,
      });
    }
  };
  walk(items);
  return out;
}

/** Walk a tree to find the MenuItem whose id matches. */
export function findMenuItem(
  items: MenuItem[],
  id: string,
): MenuItem | undefined {
  for (const rawItem of items) {
    const i = rawItem as ItemWithChildren;
    if (i.id === id) return i;
    if (i.__children) {
      const hit = findMenuItem(i.__children, id);
      if (hit) return hit;
    }
  }
  return undefined;
}

/** Derive openKeys: all top-level items marked isGroup or that have children. */
export function deriveOpenKeys(items: MenuItem[]): string[] {
  return items
    .filter((i) => {
      const item = i as ItemWithChildren;
      return item.isGroup || (item.__children && item.__children.length > 0);
    })
    .map((i) => i.id);
}
