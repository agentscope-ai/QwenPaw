import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./i18n";
import { isTauriRuntime } from "./api/config";
import { installHostExternals } from "./plugins/hostExternals";
import { registerHostModulesEager } from "./plugins/dynamicModuleRegistry";
import { installTauriConsoleNoiseFilter } from "./tauri/silenceAntdNoise";

// Expose host dependencies (React, antd, etc.) on window
// so that plugin UI modules can use them without bundling their own copies.
installHostExternals();

// Dynamic module registration - no generated files needed!
// Automatically discovers all modules in src/pages at build time
registerHostModulesEager();

if (typeof window !== "undefined" && isTauriRuntime()) {
  document.title = "QwenPaw Desktop";
  installTauriConsoleNoiseFilter();
}

createRoot(document.getElementById("root")!).render(<App />);
