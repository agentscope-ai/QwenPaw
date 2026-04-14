/**
 * Expose host dependencies on `window.__QWENPAW__` so that plugin UI modules
 * can reference React, antd, etc. without bundling their own copies.
 *
 * Plugins access them via:
 *
 * ```js
 * const { React, antd } = window.__QWENPAW__;
 * ```
 *
 * Or, if the plugin's bundler is configured with externals, it can use
 * normal `import React from "react"` and the bundler maps it to the
 * global at build time.
 *
 * Call `installHostExternals()` once at application startup (main.tsx).
 */

import React from "react";
import ReactDOM from "react-dom";
import * as antd from "antd";
import * as antdIcons from "@ant-design/icons";
import { getApiUrl, getApiToken } from "../api/config";

declare const VITE_API_BASE_URL: string;

export interface CoPawHostExternals {
  React: typeof React;
  ReactDOM: typeof ReactDOM;
  antd: typeof antd;
  antdIcons: typeof antdIcons;
  /** API base URL (e.g. "http://localhost:8001" or ""). */
  apiBaseUrl: string;
  /** Build a full API URL from a path (e.g. "/files/preview/…"). */
  getApiUrl: typeof getApiUrl;
  /** Get the current auth token. */
  getApiToken: typeof getApiToken;
}

declare global {
  interface Window {
    __QWENPAW__: CoPawHostExternals;
  }
}

export function installHostExternals(): void {
  if (window.__QWENPAW__) return;

  const apiBaseUrl =
    typeof VITE_API_BASE_URL !== "undefined" ? VITE_API_BASE_URL : "";

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
