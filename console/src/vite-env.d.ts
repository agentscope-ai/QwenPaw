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
