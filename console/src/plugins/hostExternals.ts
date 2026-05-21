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

/** Namespace object. */
export interface WindowNamespace {
  /** Shared host dependencies (React, antd, API helpers). */
  host: HostExternals;
  /**
   * Mutable module registry. Host modules are registered at startup.
   * Plugins can access and modify module exports to monkey-patch host functions.
   */
  modules: Record<string, Record<string, unknown>>;
  /** Register page routes for a plugin. */
  registerRoutes?: (pluginId: string, routes: PluginRouteDeclaration[]) => void;
  /** Register tool-call renderers for a plugin. */
  registerToolRender?: (
    pluginId: string,
    renderers: Record<string, React.FC<any>>,
  ) => void;
}

declare global {
  interface Window {
    QwenPaw: WindowNamespace;
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Install (call once in main.tsx)
// ─────────────────────────────────────────────────────────────────────────────

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

  if (!window.QwenPaw.registerRoutes) {
    window.QwenPaw.registerRoutes = (pluginId, routes) => {
      pluginSystem.addRoutes(pluginId, routes);
      console.info(
        `[plugin:${pluginId}] registerRoutes → ${routes.length} route(s)`,
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
