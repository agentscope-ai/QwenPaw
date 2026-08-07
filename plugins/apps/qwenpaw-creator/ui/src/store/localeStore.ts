import { create } from "zustand";
import i18n from "@/i18n";

interface LocaleState {
  language: string;
  setLanguage: (lang: string) => void;
}

export const useLocaleStore = create<LocaleState>((set) => ({
  language: i18n.language || "en",
  setLanguage: (lang: string) => {
    localStorage.setItem("language", lang);
    i18n.changeLanguage(lang);
    set({ language: lang });
  },
}));
