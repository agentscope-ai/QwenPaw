import { createRoot } from "react-dom/client";
import "../i18n";
import "../styles/tokens.css";
import { ThemeProvider } from "../contexts/ThemeContext";
import CloseWindowPrompt from "./CloseWindowPrompt";
import DesktopClient from "./DesktopClient";

window.addEventListener("dragover", (event) => event.preventDefault());
window.addEventListener("drop", (event) => event.preventDefault());

// The desktop document never navigates to the host. Its controls and close
// listener stay available during startup, host restarts, and connection loss.
if (
  window.location.pathname.endsWith("/tauri.html") ||
  window.location.pathname.endsWith("/index.html")
) {
  window.history.replaceState(null, "", "/");
}
createRoot(document.getElementById("root")!).render(
  <ThemeProvider syncRemote={false}>
    <CloseWindowPrompt />
    <DesktopClient />
  </ThemeProvider>,
);
