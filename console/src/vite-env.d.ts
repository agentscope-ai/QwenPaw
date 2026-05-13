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
  save_file: (url: string, filename: string) => Promise<boolean>;
}

declare global {
  // Vite build-time constants injected via define in vite.config.ts
  const VITE_API_BASE_URL: string;
  const TOKEN: string;
  const MOBILE: boolean;

  interface Window {
    pywebview?: {
      api: PyWebViewAPI;
    };
  }
}

export {};
