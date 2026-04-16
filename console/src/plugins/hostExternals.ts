/**
 * Expose host dependencies on `window.__QWENPAW__` so that plugin UI modules
 * can reference React, antd, etc. without bundling their own copies.
 *
 * Also installs `window.__registerPlugin` — the single entry point for
 * plugins to register their routes, tool renderers, and other UI
 * capabilities.
 *
 * Call `installHostExternals()` once at application startup (main.tsx).
 */

import React from "react";
import ReactDOM from "react-dom";
import * as antd from "antd";
import * as antdIcons from "@ant-design/icons";
import { getApiUrl, getApiToken } from "../api/config";

declare const VITE_API_BASE_URL: string;

// ── Host externals (shared dependencies) ────────────────────────────────

export interface CoPawHostExternals {
  React: typeof React;
  ReactDOM: typeof ReactDOM;
  antd: typeof antd;
  antdIcons: typeof antdIcons;
  apiBaseUrl: string;
  getApiUrl: typeof getApiUrl;
  getApiToken: typeof getApiToken;
}

// ── Plugin registration types ───────────────────────────────────────────

export interface PluginRouteDeclaration {
  path: string;
  component: React.ComponentType;
  label: string;
  icon?: string;
}

export interface PluginCapabilities {
  routes?: PluginRouteDeclaration[];
  toolRenderers?: Record<string, React.FC<any>>;
}

export interface PluginRegistration {
  pluginId: string;
  capabilities: PluginCapabilities;
}

/** Callback type for `window.__registerPlugin`. */
export type RegisterPluginFn = (
  pluginId: string,
  capabilities: PluginCapabilities,
) => void;

// ── Global declarations ─────────────────────────────────────────────────

declare global {
  interface Window {
    __QWENPAW__: CoPawHostExternals;
    __registerPlugin?: RegisterPluginFn;
    /** Internal: accumulated plugin registrations. */
    __pluginRegistrations__?: PluginRegistration[];
  }
}

// ── Install ─────────────────────────────────────────────────────────────

export function installHostExternals(): void {
  const apiBaseUrl =
    typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";

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

  // Always ensure the plugin registration API is available
  if (!window.__pluginRegistrations__) {
    window.__pluginRegistrations__ = [];
  }

  if (!window.__registerPlugin) {
    window.__registerPlugin = (
      pluginId: string,
      capabilities: PluginCapabilities,
    ) => {
      window.__pluginRegistrations__!.push({ pluginId, capabilities });
      console.info(`[plugin] Registered "${pluginId}"`);
    };
  }
}
