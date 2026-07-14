import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { I18nextProvider } from "react-i18next";
import { i18n } from "@/i18n";
import { SiteLanguageProvider } from "@/i18n/SiteLanguageContext";
import { ScrollToTop } from "@/components/ScrollToTop";
import App from "@/App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nextProvider i18n={i18n}>
      <BrowserRouter>
        <ScrollToTop />
        <SiteLanguageProvider>
          <App />
        </SiteLanguageProvider>
      </BrowserRouter>
    </I18nextProvider>
  </StrictMode>,
);
