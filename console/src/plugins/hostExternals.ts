/**
 * hostExternals.ts
 *
 * 1. Exposes shared host dependencies on `window.__QWENPAW__` so plugin
 *    bundles can use React / antd without bundling their own copies.
 *
 * 2. Owns the `PluginSystem` singleton — a reactive registry that plugins
 *    write to and the host reads from via subscribe/notify.
 *
 * 3. Installs two ergonomic window functions for plugin authors:
 *
 *      window.register_routes(pluginId, routes[])
 *      window.register_tool_render(pluginId, renderers{})
 *
 *    Plugins can call either, both, or neither.  Each call is additive and
 *    triggers a host re-render automatically.
 *
 * Call `installHostExternals()` once at application startup (main.tsx).
 */

import React from "react";
import ReactDOM from "react-dom";
import * as antd from "antd";
import * as antdIcons from "@ant-design/icons";
import { getApiUrl, getApiToken } from "../api/config";

declare const VITE_API_BASE_URL: string;

// ─────────────────────────────────────────────────────────────────────────────
// Public types
// ─────────────────────────────────────────────────────────────────────────────

export interface CoPawHostExternals {
  React: typeof React;
  ReactDOM: typeof ReactDOM;
  antd: typeof antd;
  antdIcons: typeof antdIcons;
  apiBaseUrl: string;
  getApiUrl: typeof getApiUrl;
  getApiToken: typeof getApiToken;
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

/** Internal per-plugin record accumulated by register_routes / register_tool_render. */
export interface PluginRegistration {
  pluginId: string;
  routes: PluginRouteDeclaration[];
  toolRenderers: Record<string, React.FC<any>>;
}

// ─────────────────────────────────────────────────────────────────────────────
// PluginSystem — reactive singleton
// ─────────────────────────────────────────────────────────────────────────────

class PluginSystem {
  private records = new Map<string, PluginRegistration>();
  private listeners = new Set<() => void>();

  // ── Write API (called by window.register_*) ──────────────────────────────

  addRoutes(pluginId: string, routes: PluginRouteDeclaration[]): void {
    const rec = this._record(pluginId);
    rec.routes.push(...routes);
    this._notify();
  }

  addToolRenderers(
    pluginId: string,
    renderers: Record<string, React.FC<any>>,
  ): void {
    const rec = this._record(pluginId);
    Object.assign(rec.toolRenderers, renderers);
    this._notify();
  }

  // ── Read API (consumed by PluginContext / usePlugins) ────────────────────

  /** Merged map of all tool renderers across all plugins. */
  getToolRenderConfig(): Record<string, React.FC<any>> {
    const out: Record<string, React.FC<any>> = {};
    for (const rec of this.records.values())
      Object.assign(out, rec.toolRenderers);
    return out;
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
      this.records.set(pluginId, { pluginId, routes: [], toolRenderers: {} });
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

declare global {
  interface Window {
    __QWENPAW__: CoPawHostExternals;
    /**
     * Register page routes for a plugin.
     * @param pluginId  - Unique plugin id (must match plugin.json `id`).
     * @param routes    - Array of route declarations.
     */
    register_routes?: (
      pluginId: string,
      routes: PluginRouteDeclaration[],
    ) => void;
    /**
     * Register tool-call renderers for a plugin.
     * @param pluginId  - Unique plugin id.
     * @param renderers - Map of tool-name → React component.
     */
    register_tool_render?: (
      pluginId: string,
      renderers: Record<string, React.FC<any>>,
    ) => void;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Install (call once in main.tsx)
// ─────────────────────────────────────────────────────────────────────────────

export function installHostExternals(): void {
  const apiBaseUrl =
    typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";

  // Shared host dependencies — plugins access these via window.__QWENPAW__
  if (!window.__QWENPAW__) {
    window.__QWENPAW__ = {
      React,
      ReactDOM,
      antd,
      antdIcons,
      apiBaseUrl,
      getApiUrl,
      getApiToken,
    };
  }

  // Plugin registration APIs
  if (!window.register_routes) {
    window.register_routes = (pluginId, routes) => {
      pluginSystem.addRoutes(pluginId, routes);
      console.info(
        `[plugin:${pluginId}] register_routes → ${routes.length} route(s)`,
      );
    };
  }

  if (!window.register_tool_render) {
    window.register_tool_render = (pluginId, renderers) => {
      pluginSystem.addToolRenderers(pluginId, renderers);
      console.info(
        `[plugin:${pluginId}] register_tool_render → ${Object.keys(
          renderers,
        ).join(", ")}`,
      );
    };
  }
}
