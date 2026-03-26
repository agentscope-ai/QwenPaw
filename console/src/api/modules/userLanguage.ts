import { request } from "../request";

export const userLanguageApi = {
  getUserLanguage: () => request<{ language: string }>("/config/user-language"),

  updateUserLanguage: (language: string) =>
    request<{ language: string }>("/config/user-language", {
      method: "PUT",
      body: JSON.stringify({ language }),
    }),
};
