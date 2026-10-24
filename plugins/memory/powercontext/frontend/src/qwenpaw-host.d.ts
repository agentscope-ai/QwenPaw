import type React from "react";

declare global {
  interface Window {
    QwenPaw: {
      host: { React: typeof React; antd: any; useLocale?: () => string };
      memoryBackends: {
        register(
          pluginId: string,
          extension: Record<string, unknown>,
        ): {
          dispose(): void;
        };
      };
    };
  }
}

export {};
