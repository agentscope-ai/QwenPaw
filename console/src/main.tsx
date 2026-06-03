import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./i18n";
import { installHostExternals } from "./plugins/hostExternals";
import { installHostSdk } from "./plugins/hostSdk/install";
import { registerHostModulesEager } from "./plugins/dynamicModuleRegistry";
// Bare side-effect imports: each file self-registers its data into
// menuRegistry / routeRegistry so consumers' first render sees them.
import "./layouts/registry/builtinMenu";
import "./layouts/registry/builtinRoutes.tsx";

// Expose host dependencies (React, antd, etc.) on window
// so that plugin UI modules can use them without bundling their own copies.
installHostExternals();

// Attach window.QwenPaw.chat (Chat customization), extend
// window.QwenPaw.host with hooks + fetch, attach window.QwenPaw.audit.
installHostSdk();

// Dynamic module registration - no generated files needed!
// Automatically discovers all modules in src/pages at build time
registerHostModulesEager();

if (typeof window !== "undefined") {
  const originalError = console.error;
  const originalWarn = console.warn;

  console.error = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    if (msg.includes(":first-child") || msg.includes("pseudo class")) {
      return;
    }
    originalError.apply(console, args as []);
  };

  console.warn = function (...args: unknown[]) {
    const msg = args[0]?.toString() || "";
    if (
      msg.includes(":first-child") ||
      msg.includes("pseudo class") ||
      msg.includes("potentially unsafe")
    ) {
      return;
    }
    originalWarn.apply(console, args as []);
  };
}

createRoot(document.getElementById("root")!).render(<App />);
