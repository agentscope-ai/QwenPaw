import { createRoot } from "react-dom/client";
import App from "./App.tsx";
import "./i18n";
import { initDebugLogCapture } from "./utils/debugLog";

if (typeof window !== "undefined") {
  const shouldIgnore = (msg: string) =>
    msg.includes(":first-child") || msg.includes("pseudo class");

  initDebugLogCapture({
    ignoreMessages: (msg) =>
      shouldIgnore(msg) || msg.includes("potentially unsafe"),
    suppressIgnoredConsole: true,
  });
}

createRoot(document.getElementById("root")!).render(<App />);
