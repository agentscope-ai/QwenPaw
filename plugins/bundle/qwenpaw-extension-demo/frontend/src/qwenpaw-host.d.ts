/**
 * Ambient declarations for `window.QwenPaw.*` consumed by this plugin.
 *
 * Kept intentionally loose (a lot of `any`) — the plugin is a smoke test, not
 * a reference implementation of type safety. Plugin authors who want strict
 * types should pull `console/src/plugins/types/qwenpaw.d.ts` into their own
 * project and uncomment the `declare global` block at its bottom.
 */
import type * as ReactNS from "react";

declare global {
  interface QwenPawHost {
    React: typeof ReactNS;
    /** antd module re-exported by the host (typed loosely on purpose). */
    antd: any;
    getApiUrl: (path: string) => string;
    getApiToken: () => string;
    // Host SDK hooks attached by installHostSdk(). Available only inside
    // plugin components rendered in the host React tree.
    useTheme?: () => "light" | "dark";
    useLocale?: () => string;
    useSelectedAgent?: () => { id: string };
    useCurrentSession?: () => { id: string } | null;
    fetch?: (path: string, init?: RequestInit) => Promise<Response>;
  }

  interface QwenPawDisposable {
    dispose(): void;
  }

  interface QwenPawMenuItem {
    id: string;
    location?: "primary.agentScoped" | "primary.settings" | "userMenu";
    parentId?: string;
    before?: string;
    after?: string;
    order?: number;
    label: string | (() => unknown);
    icon?: unknown;
    route?: string;
    visible?: () => boolean;
    isGroup?: boolean;
  }

  interface QwenPawRouteSpec {
    id: string;
    path: string;
    component: unknown;
  }

  interface QwenPawSlotOpts {
    id?: string;
    order?: number;
    visible?: () => boolean;
    before?: string;
    after?: string;
  }

  interface QwenPawMenuNamespace {
    add: (
      pluginId: string,
      item: QwenPawMenuItem | QwenPawMenuItem[],
    ) => QwenPawDisposable;
    replace: (
      pluginId: string,
      targetId: string,
      item: QwenPawMenuItem,
    ) => QwenPawDisposable;
    remove: (targetId: string) => void;
    snapshot: (location?: string) => QwenPawMenuItem[];
  }

  interface QwenPawRouteNamespace {
    add: (
      pluginId: string,
      route: QwenPawRouteSpec | QwenPawRouteSpec[],
    ) => QwenPawDisposable;
    replace: (
      pluginId: string,
      targetId: string,
      component: unknown,
    ) => QwenPawDisposable;
    wrap: (
      pluginId: string,
      targetId: string,
      wrapper: (Inner: any) => any,
    ) => QwenPawDisposable;
    remove: (targetId: string) => void;
  }

  interface QwenPawSlotNamespace {
    fill: (
      pluginId: string,
      name: string,
      render: () => unknown,
      opts?: QwenPawSlotOpts,
    ) => QwenPawDisposable;
    replace: (
      pluginId: string,
      name: string,
      render: () => unknown,
      opts?: QwenPawSlotOpts,
    ) => QwenPawDisposable;
    snapshot: () => unknown[];
  }

  interface QwenPawChatNamespace {
    welcome: {
      set: (pluginId: string, partial: any) => QwenPawDisposable;
      render: (pluginId: string, value: any) => QwenPawDisposable;
    };
    theme: { set: (pluginId: string, partial: any) => QwenPawDisposable };
    leftHeader: {
      set: (pluginId: string, partial: any) => QwenPawDisposable;
      render: (pluginId: string, node: unknown) => QwenPawDisposable;
    };
    rightHeader: {
      add: (
        pluginId: string,
        node: unknown,
        opts?: { id?: string; order?: number },
      ) => QwenPawDisposable;
    };
    sender: {
      set: (pluginId: string, partial: any) => QwenPawDisposable;
      addPrefix: (
        pluginId: string,
        node: unknown,
        opts?: { id?: string; order?: number },
      ) => QwenPawDisposable;
      addSuggestion: (
        pluginId: string,
        item: any,
      ) => QwenPawDisposable;
    };
    actions: {
      add: (pluginId: string, spec: any) => QwenPawDisposable;
    };
    requestActions: {
      add: (pluginId: string, spec: any) => QwenPawDisposable;
    };
    request: {
      render: (pluginId: string, fn: any) => QwenPawDisposable;
      prepend: (
        pluginId: string,
        fn: any,
        opts?: { id?: string; order?: number },
      ) => QwenPawDisposable;
      append: (
        pluginId: string,
        fn: any,
        opts?: { id?: string; order?: number },
      ) => QwenPawDisposable;
    };
    response: {
      render: (pluginId: string, fn: any) => QwenPawDisposable;
      prepend: (
        pluginId: string,
        fn: any,
        opts?: { id?: string; order?: number },
      ) => QwenPawDisposable;
      append: (
        pluginId: string,
        fn: any,
        opts?: { id?: string; order?: number },
      ) => QwenPawDisposable;
    };
    toolRender: (
      pluginId: string,
      toolName: string,
      render: any,
    ) => QwenPawDisposable;
    card: (
      pluginId: string,
      cardName: string,
      render: any,
    ) => QwenPawDisposable;
    disposeAll: (pluginId: string) => void;
  }

  interface QwenPawAuditRecord {
    kind: string;
    targetId?: string;
    field?: string;
    pluginId: string;
    supersededPluginId?: string;
    detail?: string;
    timestamp: number;
  }

  interface QwenPawGlobal {
    host: QwenPawHost;
    menu?: QwenPawMenuNamespace;
    route?: QwenPawRouteNamespace;
    slot?: QwenPawSlotNamespace;
    chat?: QwenPawChatNamespace;
    audit?: { overrides: () => QwenPawAuditRecord[] };
    // Legacy APIs (still work; new code should prefer the namespaces above).
    registerRoutes?: (pluginId: string, routes: any[]) => void;
    registerToolRender?: (
      pluginId: string,
      renderers: Record<string, any>,
    ) => void;
    modules?: Record<string, Record<string, unknown>>;
  }

  interface Window {
    QwenPaw: QwenPawGlobal;
  }
}

export {};
