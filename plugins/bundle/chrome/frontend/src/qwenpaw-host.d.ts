// Ambient declarations for the QwenPaw console host API.
//
// The QwenPaw console injects a shared `window.QwenPaw` object at
// runtime; we externalize `react`/`react-dom` (see `vite.config.ts`)
// and pull `React`/`antd` off `host` instead of bundling them. Without
// these declarations every access reduces to `any` and the compiler
// cannot tell us when the host contract drifts.

import type * as ReactNS from "react";

declare global {
  interface QwenPawHost {
    React: typeof ReactNS;
    antd: any;
    getApiUrl: (path: string) => string;
    getApiToken: () => string;
  }

  interface QwenPawRoute {
    path: string;
    component: unknown;
    label?: string;
    icon?: ReactNS.ReactNode;
    priority?: number;
  }

  interface QwenPawGlobal {
    host: QwenPawHost;
    registerRoutes?: (pluginId: string, routes: QwenPawRoute[]) => void;
  }

  interface Window {
    QwenPaw: QwenPawGlobal;
  }
}

export {};
