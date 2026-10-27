import { request } from "../request";

export interface ThemeDarkConfig {
  accent?: string;
  accent_bg?: string;
  surface?: string;
}

export interface ThemeConfig {
  accent?: string;
  accent_hover?: string;
  accent_bg?: string;
  radius?: string;
  dark?: ThemeDarkConfig;
}

export const themeApi = {
  get: () => request<ThemeConfig>("/config/theme"),

  update: (theme: ThemeConfig) =>
    request<ThemeConfig>("/config/theme", {
      method: "PUT",
      body: JSON.stringify(theme),
    }),

  reset: () => request<void>("/config/theme", { method: "DELETE" }),
};
