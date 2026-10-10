interface QwenPawDataDisposable {
  dispose(): void;
}

interface QwenPawDataPageRegistration {
  path: string;
  label: string;
  icon?: string;
  priority?: number;
  mount(container: HTMLElement): () => void;
}

interface QwenPawDataSdk {
  ui: {
    registerPage(
      registration: QwenPawDataPageRegistration,
    ): QwenPawDataDisposable;
  };
}

interface QwenPawDataSdkFactory {
  forApp(appId: string): QwenPawDataSdk;
}

declare global {
  interface Window {
    QwenPaw?: {
      paw?: QwenPawDataSdkFactory;
    };
  }
}

export {};
