import { createRoot } from "react-dom/client";

import type { PawSdkFactory } from "../../../../../console/src/plugins/pawapp-sdk/types";

import { App } from "./App";
import styles from "./styles.css?inline";

type PawHostWindow = Window & {
  QwenPaw?: {
    paw?: PawSdkFactory;
  };
};

function installStyles(): () => void {
  const element = document.createElement("style");
  element.dataset.qwenpawDataApp = "true";
  element.textContent = styles;
  document.head.appendChild(element);
  return () => element.remove();
}

try {
  const factory = (window as PawHostWindow).QwenPaw?.paw;
  if (!factory) {
    throw new Error(
      "This QwenPaw-Data build requires the app-scoped PawApp SDK",
    );
  }
  const paw = factory.forApp("qwenpaw-data");
  paw.ui.registerPage({
    path: "/apps/qwenpaw-data",
    label: "QwenPaw-Data",
    icon: "📊",
    priority: 20,
    mount(container) {
      const removeStyles = installStyles();
      const root = createRoot(container);
      root.render(<App />);
      return () => {
        root.unmount();
        removeStyles();
      };
    },
  });
} catch (error) {
  console.error("[qwenpaw-data] Could not register the native app", error);
}
