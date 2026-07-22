/**
 * hostExternals.ts
 *
 * Exposes shared host dependencies and a reactive plugin registry on
 * `window.QwenPaw` so plugin bundles can register routes and tool renderers
 * without bundling their own copies of React / antd.
 *
 * Call `installHostExternals()` once at application startup (main.tsx).
 */

import React from "react";
import ReactDOM from "react-dom";
import * as antd from "antd";
import * as antdIcons from "@ant-design/icons";
import { getApiUrl, getApiToken } from "../api/config";
import {
  buildAuditNamespace,
  buildMenuNamespace,
  buildRouteNamespace,
  buildSlotNamespace,
  type QwenPawAuditNamespace,
  type QwenPawMenuNamespace,
  type QwenPawRouteNamespace,
  type QwenPawSlotNamespace,
} from "./registry/sdk";
import { menuRegistry, routeRegistry } from "./registry/store";
import type {
  HostAgentInfo,
  HostSessionInfo,
  HostThemeMode,
  QwenPawChatNamespace,
} from "./types/qwenpaw";

declare const VITE_API_BASE_URL: string;

// ─────────────────────────────────────────────────────────────────────────────
// Public types
// ─────────────────────────────────────────────────────────────────────────────

/** Shared host dependencies exposed to plugin bundles via `window.QwenPaw.host`. */
export interface HostExternals {
  React: typeof React;
  ReactDOM: typeof ReactDOM;
  antd: typeof antd;
  antdIcons: typeof antdIcons;
  apiBaseUrl: string;
  getApiUrl: typeof getApiUrl;
  getApiToken: typeof getApiToken;
  // ── Hooks + helpers attached later by installHostSdk() ─────────────────────
  useTheme?: () => HostThemeMode;
  useLocale?: () => string;
  useSelectedAgent?: () => HostAgentInfo;
  useCurrentSession?: () => HostSessionInfo | null;
  getSelectedAgentId?: () => string;
  getCurrentSessionId?: () => string | null;
  fetch?: (path: string, init?: RequestInit) => Promise<Response>;
}

export interface PluginRouteDeclaration {
  /** Full URL path, e.g. "/plugin/my-plugin/dashboard". */
  path: string;
  component: React.ComponentType;
  /** Sidebar display label. */
  label: string;
  /** Emoji or short icon text. */
  icon?: string;
  /** Lower number = appears earlier in sidebar. Defaults to 0. */
  priority?: number;
}

/** Internal per-plugin registration record. */
export interface PluginRegistration {
  pluginId: string;
  /** When true, this plugin's tool renderers are treated as fallback defaults.
   *  External (non-builtin) renderers for the same tool name take priority. */
  isBuiltin: boolean;
  routes: PluginRouteDeclaration[];
  toolRenderers: Record<string, React.FC<any>>;
}

// ─────────────────────────────────────────────────────────────────────────────
// PluginSystem — reactive singleton
// ─────────────────────────────────────────────────────────────────────────────

class PluginSystem {
  private records = new Map<string, PluginRegistration>();
  private listeners = new Set<() => void>();

  // ── Write API ───────────────────────────────────────────────────────────

  addRoutes(pluginId: string, routes: PluginRouteDeclaration[]): void {
    const rec = this._record(pluginId);
    rec.routes.push(...routes);
    this._notify();
  }

  addToolRenderers(
    pluginId: string,
    renderers: Record<string, React.FC<any>>,
    options?: { isBuiltin?: boolean },
  ): void {
    const rec = this._record(pluginId);
    if (options?.isBuiltin) rec.isBuiltin = true;
    Object.assign(rec.toolRenderers, renderers);
    this._notify();
  }

  // ── Read API (consumed by PluginContext / usePlugins) ────────────────────

  /** Merged map of all tool renderers across all plugins.
   *  Builtin renderers are applied first, then external plugin renderers
   *  overlay on top — so external plugins take priority over builtins. */
  getToolRenderConfig(): Record<string, React.FC<any>> {
    const builtinRenderers: Record<string, React.FC<any>> = {};
    const externalRenderers: Record<string, React.FC<any>> = {};
    for (const rec of this.records.values()) {
      const target = rec.isBuiltin ? builtinRenderers : externalRenderers;
      Object.assign(target, rec.toolRenderers);
    }
    return { ...builtinRenderers, ...externalRenderers };
  }

  /** Flat list of all page routes across all plugins, sorted by priority. */
  getRoutes(): PluginRouteDeclaration[] {
    const out: PluginRouteDeclaration[] = [];
    for (const rec of this.records.values()) out.push(...rec.routes);
    return out.sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0));
  }

  // ── Subscription ─────────────────────────────────────────────────────────

  /** Subscribe to any registration change. Returns an unsubscribe function. */
  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  // ── Internals ────────────────────────────────────────────────────────────

  private _record(pluginId: string): PluginRegistration {
    if (!this.records.has(pluginId)) {
      this.records.set(pluginId, {
        pluginId,
        isBuiltin: false,
        routes: [],
        toolRenderers: {},
      });
    }
    return this.records.get(pluginId)!;
  }

  private _notify(): void {
    this.listeners.forEach((fn) => fn());
  }
}

/** Global singleton — imported by PluginContext to subscribe to changes. */
export const pluginSystem = new PluginSystem();

// ─────────────────────────────────────────────────────────────────────────────
// Global declarations
// ─────────────────────────────────────────────────────────────────────────────

/** Namespace object. */
export interface WindowNamespace {
  /** Shared host dependencies (React, antd, API helpers). */
  host: HostExternals;
  /**
   * Mutable module registry. Host modules are registered at startup.
   * Plugins can access and modify module exports to monkey-patch host functions.
   */
  modules: Record<string, Record<string, unknown>>;
  /** Register page routes for a plugin. Translates to menu.add + route.add. */
  registerRoutes?: (pluginId: string, routes: PluginRouteDeclaration[]) => void;
  /** Register tool-call renderers for a plugin. */
  registerToolRender?: (
    pluginId: string,
    renderers: Record<string, React.FC<any>>,
  ) => void;
  /** Console-wide plugin Menu API. Attached by installHostExternals(). */
  menu?: QwenPawMenuNamespace;
  /** Console-wide plugin Route API. */
  route?: QwenPawRouteNamespace;
  /** Console-wide plugin Slot API (header.left, sider.bottom, …). */
  slot?: QwenPawSlotNamespace;
  /** Chat-surface customization API. Attached by installHostSdk(). */
  chat?: QwenPawChatNamespace;
  /** Override audit log (debug). Attached by installHostExternals(). */
  audit?: QwenPawAuditNamespace;
}

declare global {
  interface Window {
    QwenPaw: WindowNamespace;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Install (call once in main.tsx)
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Synthesize the `plugins-group` parent menu the first time a legacy
 * `registerRoutes` call lands. Idempotent via menuRegistry snapshot check —
 * if a plugin (or test) has already created `plugins-group` (via the new API
 * or a prior synthesis call), we skip. No mutable module flag, so behaviour
 * is correct under test reset / hot reload.
 */
function ensurePluginsGroup(): void {
  const exists = menuRegistry
    .snapshot("primary.settings")
    .some((i) => i.id === "plugins-group");
  if (exists) return;
  menuRegistry.addBuiltin([
    {
      id: "plugins-group",
      location: "primary.settings",
      label: "Plugins",
      isGroup: true,
      order: 999,
    },
  ]);
}

export function installHostExternals(): void {
  const apiBaseUrl =
    typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";

  if (!window.QwenPaw) {
    (window as any).QwenPaw = {} as WindowNamespace;
  }

  if (!window.QwenPaw.host) {
    window.QwenPaw.host = {
      React,
      ReactDOM,
      antd,
      antdIcons,
      apiBaseUrl,
      getApiUrl,
      getApiToken,
    };
  }

  // ── Console-wide extension API ─────────────────────────────────────────
  if (!window.QwenPaw.menu) window.QwenPaw.menu = buildMenuNamespace();
  if (!window.QwenPaw.route) window.QwenPaw.route = buildRouteNamespace();
  if (!window.QwenPaw.slot) window.QwenPaw.slot = buildSlotNamespace();
  if (!window.QwenPaw.audit) window.QwenPaw.audit = buildAuditNamespace();

  // ── Back-compat shim ───────────────────────────────────────────────────
  // Legacy registerRoutes(pluginId, routes[]) fans out to:
  //   1. route.add with id = `legacy:<pluginId>:<path>`
  //   2. menu.add under the synthesized `plugins-group` (settings location).
  // Visual output matches the pre-refactor Sidebar plugins-group rendering.
  //
  // EXCEPTION: PawApp routes (path starting with `/apps/`) register the
  // route only — NO sidebar menu entry. PawApps are reachable exclusively
  // through the App Center, which renders them inline via routeRegistry.
  if (!window.QwenPaw.registerRoutes) {
    window.QwenPaw.registerRoutes = (pluginId, routes) => {
      for (const r of routes) {
        const id = `legacy:${pluginId}:${r.path.replace(/^\//, "")}`;
        routeRegistry.add(pluginId, {
          id,
          path: r.path,
          component: r.component,
        });

        // PawApp pages are surfaced only in the App Center — never as a
        // standalone sidebar menu item.
        if (/^\/apps\//.test(r.path)) continue;

        ensurePluginsGroup();
        menuRegistry.add(pluginId, {
          id,
          location: "primary.settings",
          parentId: "plugins-group",
          label: r.label,
          // Emoji string in original API → wrap to match prior Sidebar font-size styling.
          icon: React.createElement(
            "span",
            { style: { fontSize: 16 } },
            r.icon,
          ),
          route: id,
          order: r.priority ?? 0,
        });
      }
      // Keep the legacy pluginSystem in sync so usePlugins().pluginRoutes still works
      // for any consumer that has not migrated yet (e.g. the chat-extension branch).
      pluginSystem.addRoutes(pluginId, routes);
      console.info(
        `[plugin:${pluginId}] registerRoutes → ${routes.length} route(s) (translated to menu+route)`,
      );
    };
  }

  if (!window.QwenPaw.registerToolRender) {
    window.QwenPaw.registerToolRender = (pluginId, renderers) => {
      pluginSystem.addToolRenderers(pluginId, renderers);
      console.info(
        `[plugin:${pluginId}] registerToolRender → ${Object.keys(
          renderers,
        ).join(", ")}`,
      );
    };
  }
}
