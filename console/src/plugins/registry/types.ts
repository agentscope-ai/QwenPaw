/**
 * registry/types.ts — public shapes for the console-wide plugin extension API.
 *
 * Three concepts:
 *   - Menu  → sidebar entries with location/parentId/before/after/order
 *   - Route → pages with add/replace/wrap
 *   - Slot  → named layout fill points (header.left, sider.bottom, …)
 *
 * Plugin-facing surface lives in `sdk.ts`; this file is the structural ground
 * truth used by `store.ts`, hooks, and `Slot.tsx`.
 */
import type React from "react";

// ─────────────────────────────────────────────────────────────────────────────
// Disposable
// ─────────────────────────────────────────────────────────────────────────────

export interface Disposable {
  dispose(): void;
}

/** Combine multiple Disposables into one. Errors per-dispose are swallowed + logged. */
export function combineDisposables(...d: Disposable[]): Disposable {
  return {
    dispose() {
      for (const it of d) {
        try {
          it.dispose();
        } catch (err) {
          console.warn("[QwenPaw] Disposable threw on dispose:", err);
        }
      }
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Menu
// ─────────────────────────────────────────────────────────────────────────────

export type MenuLocation =
  | "primary.agentScoped" // Sidebar Menu #1 (agent-bound entries: inbox, control, agent-group)
  | "primary.settings" //   Sidebar Menu #2 (global settings + plugins-group)
  | "userMenu"; //          Reserved for future avatar-dropdown items

export interface MenuItem {
  /** Globally unique id, e.g. "core.workspace" / "cloudpaw.a2a". */
  id: string;
  /** Which Sidebar bucket. Defaults to "primary.settings". */
  location?: MenuLocation;
  /**
   * If set, this item is a CHILD of the named parent (groups: "core.control-group",
   * "core.agent-group", "core.settings-group", "plugins-group", …).
   * Items without parentId render at top level within their location bucket.
   */
  parentId?: string;
  /** Relative-position constraint: render before the item with this id. */
  before?: string;
  /** Relative-position constraint: render after the item with this id. */
  after?: string;
  /** Numeric fallback when before/after can't disambiguate. Lower renders first. */
  order?: number;
  /**
   * Display label. String for static, function for i18n + dynamic decoration
   * (e.g. unread badge). Adapter wraps `null` returns in a Fragment.
   */
  label: string | (() => React.ReactNode);
  /**
   * Icon. ComponentType for SDK / lucide icons (rendered with size=16); ReactNode for
   * plain emoji/img. We accept `ComponentType<any>` to allow any icon library
   * (Spark, lucide, antd) whose props accept a `size` field even if typed loosely.
   */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  icon?: React.ComponentType<any> | React.ReactNode;
  /** Route id to navigate to when clicked. If absent, item is non-interactive (group header / divider). */
  route?: string;
  /** Hide this entry when callback returns false. Defaults to always visible. */
  visible?: () => boolean;
  /** Render as group header (children appear nested under it). */
  isGroup?: boolean;
  /** Render as horizontal divider. id is still required for de-dup. */
  divider?: boolean;
}

// ─────────────────────────────────────────────────────────────────────────────
// Route
// ─────────────────────────────────────────────────────────────────────────────

/** A registered route entry (added via builtinRoutes or QwenPaw.route.add). */
export interface Route {
  /** Stable id, e.g. "core.chat" / "cloudpaw.a2a". */
  id: string;
  /** URL path. Supports react-router patterns, including "/chat/*". */
  path: string;
  /** Lazy or eager component. */
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  component: React.ComponentType<any>;
}

/**
 * Onion-style wrapper. Receives the inner component (current resolved render)
 * and returns the new component to render. Multiple wraps compose;
 * later-registered wrappers wrap the outside (see resolveRoute in store.ts).
 */
export type RouteWrapper = (
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  Inner: React.ComponentType<any>,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
) => React.ComponentType<any>;

// ─────────────────────────────────────────────────────────────────────────────
// Slot
// ─────────────────────────────────────────────────────────────────────────────

/** A free-form name like "header.left" / "sider.bottom". Host curates the list. */
export type SlotName = string;

export type SlotKind = "fill" | "replace";

export interface SlotOpts {
  /** Stable id for this fill; lets other fills target with before/after. */
  id?: string;
  /** Numeric fallback. Lower renders first. */
  order?: number;
  /** Render only when this returns true. */
  visible?: () => boolean;
  /** Render strictly before another fill (same slot). fill-mode only. */
  before?: string;
  /** Render strictly after another fill (same slot). fill-mode only. */
  after?: string;
}

export type SlotRenderer = () => React.ReactNode;

export interface SlotInfo {
  name: SlotName;
  kind: SlotKind;
  source: string;
  id?: string;
  order?: number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Audit
// ─────────────────────────────────────────────────────────────────────────────

export type AuditKind =
  | "menu.add"
  | "menu.replace"
  | "menu.dispose"
  | "menu.conflict"
  | "route.add"
  | "route.replace"
  | "route.wrap"
  | "route.dispose"
  | "route.conflict"
  | "slot.fill"
  | "slot.replace"
  | "slot.dispose"
  | "slot.error";

export interface OverrideRecord {
  kind: AuditKind;
  /** What was acted on: menuId / routeId / slotName / etc. */
  targetId: string;
  /** Who acted: pluginId, "core" for host builtins, "core:auto-…" for synthesized entries. */
  pluginId: string;
  /** Previous owner when an override took effect. */
  supersededPluginId?: string;
  /** Free-form details (conflict reason, error message, slot id, …). */
  detail?: string;
  timestamp: number;
}
