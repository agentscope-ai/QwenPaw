/// <reference types="vite/client" />

declare module "dayjs" {
  interface Dayjs {
    fromNow(withoutSuffix?: boolean): string;
  }
}

declare module "*.less" {
  const classes: { [key: string]: string };
  export default classes;
}

interface PyWebViewAPI {
  open_external_link?: (url: string) => void;
  open_in_explorer?: (path: string) => Promise<boolean>;
  save_file?: (
    url: string,
    filename: string,
    headers?: Record<string, string>,
  ) => Promise<boolean>;
}

declare global {
  interface Window {
    pywebview?: {
      api: PyWebViewAPI;
    };
  }
}

export {};
