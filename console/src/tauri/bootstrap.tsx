import { createRoot } from "react-dom/client";
import "../i18n";
import { ThemeProvider } from "../contexts/ThemeContext";
import BackendReadyGate from "./BackendReadyGate";

createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <BackendReadyGate>{null}</BackendReadyGate>
  </ThemeProvider>,
);
