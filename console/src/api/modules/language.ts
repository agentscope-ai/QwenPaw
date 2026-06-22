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

  getCloseBehavior: () =>
    request<{ close_behavior: "minimize" | "quit" }>(
      "/settings/close-behavior",
    ),

  updateCloseBehavior: (close_behavior: "minimize" | "quit") =>
    request<{ close_behavior: "minimize" | "quit" }>(
      "/settings/close-behavior",
      {
        method: "PUT",
        body: JSON.stringify({ close_behavior }),
      },
    ),
};

/** @deprecated Use settingsApi instead */
export const languageApi = settingsApi;
