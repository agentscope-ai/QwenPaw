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

/** Only the handoff fields consumed by the standalone Data app. */
export interface QwenPawDataHandoff {
  target_app_id: string;
  context: {
    project_ref: {
      app_id: string;
      project_id: string;
      kind: string;
    };
    view_id?: string | null;
  };
}

export interface QwenPawDataSdk {
  apps: {
    resolveHandoff(handoffId: string): Promise<QwenPawDataHandoff>;
  };
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
