import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./i18n";
import { installHostExternals } from "./plugins/hostExternals";
// Bare side-effect imports: each file self-registers its data into
// menuRegistry / routeRegistry so consumers' first render sees them.
import "./layouts/registry/builtinMenu";
import "./layouts/registry/builtinRoutes.tsx";

// Expose host dependencies (React, antd, etc.) on window
// so that plugin UI modules can use them without bundling their own copies.
installHostExternals();

if (typeof window !== "undefined") {
  // Prevent the browser/WebView from navigating away (replacing the whole
  // app) when a file is dropped outside a drop zone like the chat sender.
  // The Tauri window disables native drag-drop interception so OS file
  // drags reach the page as HTML5 drag events; any drop not consumed by a
  // drop zone would otherwise open the file directly. Drop zones stop
  // propagation, so this only sees unhandled drops. Scoped to file drags
  // to keep element drag-and-drop (e.g. queue reordering) untouched.
  const isFileDrag = (e: DragEvent) =>
    !!e.dataTransfer && Array.from(e.dataTransfer.types).includes("Files");
  window.addEventListener("dragover", (e) => {
    if (isFileDrag(e)) e.preventDefault();
  });
  window.addEventListener("drop", (e) => {
    if (isFileDrag(e)) e.preventDefault();
  });

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
