import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./i18n";
import { installHostExternals } from "./plugins/hostExternals";
import { installHostSdk } from "./plugins/hostSdk/install";
import { registerHostModulesDynamic } from "./plugins/dynamicModuleRegistry";
import { registerBuiltinCards } from "./components/Chat/ToolCards/registerBuiltinCards";
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

// Register built-in tool card renderers into the PluginSystem
// so ChatV1 (@agentscope-ai/chat) picks them up via customToolRenderConfig.
registerBuiltinCards();

// Dynamic module registration — fire-and-forget. Pages register into
// `moduleRegistry` as they are lazy-loaded; this background pass pre-warms
// the registry so `window.QwenPaw.modules.<page>` is populated soon after
// startup without blocking the first paint (eager mode used to synchronously
// pull all 233 page modules + transitive deps into the main thread).
void registerHostModulesDynamic();

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
