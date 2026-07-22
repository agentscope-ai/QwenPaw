import { createRoot } from "react-dom/client";
import "../i18n";
import { ThemeProvider } from "../contexts/ThemeContext";
import BackendReadyGate from "./BackendReadyGate";
import CloseWindowPrompt from "./CloseWindowPrompt";

createRoot(document.getElementById("root")!).render(
  <ThemeProvider>
    <CloseWindowPrompt />
    <BackendReadyGate>{null}</BackendReadyGate>
  </ThemeProvider>,
);
