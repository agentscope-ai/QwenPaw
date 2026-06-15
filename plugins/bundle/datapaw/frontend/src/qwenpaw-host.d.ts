/**
 * Ambient declarations for the QwenPaw host API surface that the
 * DataPaw plugin bundle consumes. Mirrors `qwenpaw-pet/frontend/src/
 * qwenpaw-host.d.ts` so both plugins type-check against the same
 * contract; if the host adds or renames anything, both must update.
 */

import type * as ReactNS from "react";
import type * as ReactDOMNS from "react-dom";

declare global {
  /** Shared host dependencies exposed at `window.QwenPaw.host`. */
  interface QwenPawHost {
    React: typeof ReactNS;
    ReactDOM: typeof ReactDOMNS;
    /**
     * antd module re-exported by the host. Typed as `any` because antd's
     * public types are huge and the plugin destructures named exports
     * dynamically; a structural `any` keeps consumers compiling without
     * pinning to a specific antd version.
     */
    antd: any;
    /** @ant-design/icons re-exported by the host. */
    antdIcons: any;
    /** Resolve a console-relative API path to an absolute URL. */
    getApiUrl: (path: string) => string;
    /** Bearer token for QwenPaw API calls (may be ""). */
    getApiToken: () => string;
    /** Optional: base URL the host was built against. */
    apiBaseUrl?: string;
  }

  /**
   * A single sidebar route the plugin contributes. The host renders the
   * component when the user navigates to `path`.
   */
  interface QwenPawRoute {
    /** Full URL path, e.g. `/plugin/datapaw`. */
    path: string;
    /** React component the host mounts inside its layout. */
    component: ReactNS.ComponentType<any>;
    /** Sidebar display label. */
    label?: string;
    /** Emoji or short icon text. */
    icon?: string;
    /** Lower number = earlier in the sidebar. */
    priority?: number;
  }

  interface QwenPawDisposable {
    dispose(): void;
  }

  type QwenPawLocalized<T> = T | ((locale: string) => T);

  interface QwenPawChatWelcome {
    set(
      pluginId: string,
      partial: Partial<{
        greeting: QwenPawLocalized<string | ReactNS.ReactNode>;
        description: QwenPawLocalized<string | ReactNS.ReactNode>;
        avatar: QwenPawLocalized<string | ReactNS.ReactNode>;
        nick: QwenPawLocalized<string | ReactNS.ReactNode>;
        prompts: QwenPawLocalized<ReactNS.ReactNode[]>;
      }>,
    ): QwenPawDisposable;
  }

  interface QwenPawChatResponse {
    set(
      pluginId: string,
      partial: Partial<{
        avatar: QwenPawLocalized<string | ReactNS.ReactNode>;
        nick: QwenPawLocalized<string | ReactNS.ReactNode>;
      }>,
    ): QwenPawDisposable;
  }

  interface QwenPawChatSender {
    addPrefix(
      pluginId: string,
      node: ReactNS.ReactNode,
      opts?: { id?: string; order?: number },
    ): QwenPawDisposable;
  }

  interface QwenPawChatNamespace {
    welcome?: QwenPawChatWelcome;
    response?: QwenPawChatResponse;
    sender: QwenPawChatSender;
    card?: (
      pluginId: string,
      cardName: string,
      render: ReactNS.FC<Record<string, unknown>>,
    ) => QwenPawDisposable;
  }

  interface QwenPawGlobal {
    host: QwenPawHost;
    /** Mutable host module registry (used by hot-patch plugins). */
    modules?: Record<string, Record<string, unknown>>;
    /** Register sidebar/page routes for a plugin. */
    registerRoutes?: (pluginId: string, routes: QwenPawRoute[]) => void;
    /** Register chat tool renderers for a plugin. */
    registerToolRender?: (
      pluginId: string,
      renderers: Record<string, ReactNS.FC<any>>,
    ) => void;
    /** Merge plugin translation bundles into host i18next. */
    registerI18n?: (
      pluginId: string,
      bundles: Record<string, Record<string, unknown>>,
    ) => void;
    /** Chat-surface customization (welcome, sender prefix, cards, …). */
    chat?: QwenPawChatNamespace;
  }

  interface Window {
    QwenPaw: QwenPawGlobal;
  }
}

// -----------------------------------------------------------------------------
// Build-time defines (forwarded from vite.config.ts `define`). Kept empty in
// the plugin build — the bundle always speaks to the same origin as the host
// and reads the bearer from localStorage.
// -----------------------------------------------------------------------------
declare const VITE_API_BASE_URL: string;
declare const TOKEN: string;
declare const MOBILE: boolean;
/** Set to `true` in `vite.config.ts` — this frontend only builds as a host plugin. */
declare const __DATAPAW_PLUGIN_EMBED__: boolean;

// -----------------------------------------------------------------------------
// Tiny module shims so the upstream console sources compile without us having
// to pull in `@types/dayjs` / `vite/client` extensions a second time.
// -----------------------------------------------------------------------------
declare module "*.less" {
  const classes: { [key: string]: string };
  export default classes;
}
declare module "*.module.less" {
  const classes: { [key: string]: string };
  export default classes;
}
declare module "*.css" {
  const classes: { [key: string]: string };
  export default classes;
}
declare module "*.png" {
  const url: string;
  export default url;
}
declare module "*.png?url" {
  const url: string;
  export default url;
}
declare module "dayjs" {
  interface Dayjs {
    fromNow(withoutSuffix?: boolean): string;
  }
}

interface PyWebViewAPI {
  open_external_link: (url: string) => void;
}

declare global {
  interface Window {
    pywebview?: {
      api: PyWebViewAPI;
    };
  }
}

export {};
