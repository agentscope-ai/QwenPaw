import { request } from "../request";

export interface PublicUrlResponse {
  public_url: string;
  source: "settings" | "env" | "auto";
}

export const settingsApi = {
  getPublicUrl: () => request<PublicUrlResponse>("/settings/public-url"),

  setPublicUrl: (publicUrl: string) =>
    request<PublicUrlResponse>("/settings/public-url", {
      method: "PUT",
      body: JSON.stringify({ public_url: publicUrl }),
    }),

  clearPublicUrl: () =>
    request<PublicUrlResponse>("/settings/public-url", {
      method: "DELETE",
    }),
};
