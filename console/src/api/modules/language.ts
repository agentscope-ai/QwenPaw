import { request } from "../request";

export const settingsApi = {
  getLanguage: () => request<{ language: string }>("/settings/language"),

  updateLanguage: (language: string) =>
    request<{ language: string }>("/settings/language", {
      method: "PUT",
      body: JSON.stringify({ language }),
    }),

  getUploadLimit: () =>
    request<{ upload_max_size_mb: number | null }>("/settings/upload-limit"),
};

/** @deprecated Use settingsApi instead */
export const languageApi = settingsApi;
