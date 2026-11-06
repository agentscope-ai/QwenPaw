import { createRoot } from "react-dom/client";
import "../i18n";
import "../styles/tokens.css";
import DesktopClient from "./DesktopClient";

const preventFileNavigation = (event: DragEvent) => {
  if (event.dataTransfer?.types.includes("Files")) event.preventDefault();
};
window.addEventListener("dragover", preventFileNavigation);
window.addEventListener("drop", preventFileNavigation);

// The desktop document never navigates to the host. Its controls and close
// listener stay available during startup, host restarts, and connection loss.
if (
  window.location.pathname.endsWith("/tauri.html") ||
  window.location.pathname.endsWith("/index.html")
) {
  window.history.replaceState(null, "", "/");
}
createRoot(document.getElementById("root")!).render(<DesktopClient />);
