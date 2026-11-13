import "@/i18n";
import { createRoot } from "react-dom/client";
import App from "@/app/App";
import { AppProviders } from "@/app/providers";
import "./app/globals.css";

createRoot(document.getElementById("root")!).render(
  <AppProviders>
    <App />
  </AppProviders>,
);
