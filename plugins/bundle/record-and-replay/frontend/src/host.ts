import type * as ReactNS from "react";
import type * as AntdNS from "antd";
import type * as IconsNS from "@ant-design/icons";

export interface RecordingPluginHost {
  host: {
    React: typeof ReactNS;
    antd: typeof AntdNS;
    antdIcons: typeof IconsNS;
    useLocale: () => string;
    useSelectedAgent: () => { id: string };
    fetch: (path: string, init?: RequestInit) => Promise<Response>;
  };
  chat: {
    rightHeader: {
      add: (
        id: string,
        node: ReactNS.ReactNode,
        options?: { id?: string; order?: number },
      ) => unknown;
    };
  };
  route: {
    add: (
      pluginId: string,
      route: {
        id: string;
        path: string;
        component: ReactNS.ComponentType;
      },
    ) => unknown;
  };
  menu: {
    add: (
      pluginId: string,
      item: {
        id: string;
        location: "primary.settings";
        label: string;
        icon: ReactNS.ReactNode;
        route: string;
        order: number;
      },
    ) => unknown;
  };
}

export const qwenpaw = (window as unknown as { QwenPaw: RecordingPluginHost })
  .QwenPaw;
export const host = qwenpaw.host;
