import { request } from "../request";

export const languageApi = {
  getLanguage: () => request<{ language: string }>("/settings/language"),

  updateLanguage: (language: string) =>
    request<{ language: string }>("/settings/language", {
      method: "PUT",
      body: JSON.stringify({ language }),
    }),
};
