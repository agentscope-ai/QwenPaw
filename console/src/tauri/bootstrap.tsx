import { createRoot } from "react-dom/client";
import "../i18n";
import { ThemeProvider } from "../contexts/ThemeContext";
import BackendReadyGate from "./BackendReadyGate";
import CloseWindowPrompt from "./CloseWindowPrompt";

// The window has dragDropEnabled=false (see tauri.conf.json, issue #6297),
// so OS file drags arrive as HTML5 drag events. Block the default "navigate
// to dropped file" behavior on this bootstrap page; the console app installs
// its own guard in main.tsx after navigation.
window.addEventListener("dragover", (e) => e.preventDefault());
window.addEventListener("drop", (e) => e.preventDefault());

createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <CloseWindowPrompt />
    <BackendReadyGate>{null}</BackendReadyGate>
  </ThemeProvider>,
);
