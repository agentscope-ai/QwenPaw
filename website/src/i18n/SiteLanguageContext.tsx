import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { i18n, LANG_KEY, type Lang } from "@/i18n";

function getInitialLang(): Lang {
  const params = new URLSearchParams(window.location.search);
  const urlLang = params.get("lang");
  if (urlLang === "en" || urlLang === "zh") {
    localStorage.setItem(LANG_KEY, urlLang);
    return urlLang;
  }
  const v = localStorage.getItem(LANG_KEY);
  return v === "en" ? "en" : "zh";
}

export type SiteLanguageContextValue = {
  lang: Lang;
  toggleLang: () => void;
};

const SiteLanguageContext = createContext<SiteLanguageContextValue | null>(
  null,
);

export function SiteLanguageProvider({ children }: { children: ReactNode }) {
  const [lang, setLang] = useState<Lang>(getInitialLang);

  useEffect(() => {
    void i18n.changeLanguage(lang);
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang]);

  const toggleLang = useCallback(() => {
    setLang((prev) => {
      const next: Lang = prev === "zh" ? "en" : "zh";
      localStorage.setItem(LANG_KEY, next);
      return next;
    });
  }, []);

  const value: SiteLanguageContextValue = { lang, toggleLang };

  return (
    <SiteLanguageContext.Provider value={value}>
      {children}
    </SiteLanguageContext.Provider>
  );
}

export function useSiteLanguage(): SiteLanguageContextValue {
  const ctx = useContext(SiteLanguageContext);
  if (!ctx) {
    throw new Error(
      "useSiteLanguage must be used within <SiteLanguageProvider>",
    );
  }
  return ctx;
}
