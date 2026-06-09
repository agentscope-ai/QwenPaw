import type * as ReactNS from "react";

export interface HostBundle {
  React: typeof ReactNS;
  antd: {
    Card: React.ComponentType<any>;
    Table: React.ComponentType<any>;
    Tag: React.ComponentType<any>;
    Spin: React.ComponentType<any>;
    Button: React.ComponentType<any>;
    Popover: React.ComponentType<any>;
    Typography: { Text: React.ComponentType<any> };
    message?: { success: (msg: string) => void; error: (msg: string) => void };
    [key: string]: any;
  };
  getApiUrl: (path: string) => string;
  getApiToken: () => string;
}
