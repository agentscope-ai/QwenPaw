/**
 * registry/sdk.ts — public plugin API factory.
 *
 * `buildPluginSdk()` returns an object suitable for attaching to
 * `window.QwenPaw.{menu, route, slot, audit}`. All plugin-facing methods take
 * `pluginId` as their first argument (mirrors existing
 * `registerRoutes("cloudpaw", …)` style — no async "currentPlugin" magic).
 *
 * Wired by `hostExternals.ts → installHostExternals()` in Commit 3.
 */
import type {
  Disposable,
  MenuItem,
  OverrideRecord,
  Route,
  RouteWrapper,
  SlotInfo,
  SlotName,
  SlotOpts,
  SlotRenderer,
} from "./types";
import { menuRegistry, routeRegistry, slotRegistry } from "./store";
import { auditStore } from "./audit";

// ─────────────────────────────────────────────────────────────────────────────
// Plugin-facing namespaces
// ─────────────────────────────────────────────────────────────────────────────

export interface QwenPawMenuNamespace {
  add(pluginId: string, item: MenuItem | MenuItem[]): Disposable;
  replace(pluginId: string, targetId: string, item: MenuItem): Disposable;
  remove(targetId: string): void;
  snapshot(location?: Parameters<typeof menuRegistry.snapshot>[0]): MenuItem[];
}

export interface QwenPawRouteNamespace {
  add(pluginId: string, route: Route | Route[]): Disposable;
  replace(
    pluginId: string,
    targetId: string,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    component: React.ComponentType<any>,
  ): Disposable;
  wrap(pluginId: string, targetId: string, wrapper: RouteWrapper): Disposable;
  remove(targetId: string): void;
}

export interface QwenPawSlotNamespace {
  fill(
    pluginId: string,
    name: SlotName,
    render: SlotRenderer,
    opts?: SlotOpts,
  ): Disposable;
  replace(
    pluginId: string,
    name: SlotName,
    render: SlotRenderer,
    opts?: SlotOpts,
  ): Disposable;
  snapshot(): SlotInfo[];
}

export interface QwenPawAuditNamespace {
  overrides(): OverrideRecord[];
}

// ─────────────────────────────────────────────────────────────────────────────
// Internal helpers
// ─────────────────────────────────────────────────────────────────────────────

import { combineDisposables } from "./types";

function asArray<T>(x: T | T[]): T[] {
  return Array.isArray(x) ? x : [x];
}

// ─────────────────────────────────────────────────────────────────────────────
// Factories
// ─────────────────────────────────────────────────────────────────────────────

export function buildMenuNamespace(): QwenPawMenuNamespace {
  return {
    add: (pluginId, item) => {
      const items = asArray(item);
      const ds = items.map((i) => menuRegistry.add(pluginId, i));
      return combineDisposables(...ds);
    },
    replace: (pluginId, targetId, item) =>
      menuRegistry.replace(pluginId, targetId, item),
    remove: (targetId) => menuRegistry.remove(targetId),
    snapshot: (location) => menuRegistry.snapshot(location),
  };
}

export function buildRouteNamespace(): QwenPawRouteNamespace {
  return {
    add: (pluginId, route) => {
      const routes = asArray(route);
      const ds = routes.map((r) => routeRegistry.add(pluginId, r));
      return combineDisposables(...ds);
    },
    replace: (pluginId, targetId, component) =>
      routeRegistry.replace(pluginId, targetId, component),
    wrap: (pluginId, targetId, wrapper) =>
      routeRegistry.wrap(pluginId, targetId, wrapper),
    remove: (targetId) => routeRegistry.remove(targetId),
  };
}

export function buildSlotNamespace(): QwenPawSlotNamespace {
  return {
    fill: (pluginId, name, render, opts) =>
      slotRegistry.fill(pluginId, name, render, opts),
    replace: (pluginId, name, render, opts) =>
      slotRegistry.replace(pluginId, name, render, opts),
    snapshot: () => slotRegistry.snapshotAll(),
  };
}

export function buildAuditNamespace(): QwenPawAuditNamespace {
  return {
    overrides: () => auditStore.overrides(),
  };
}
