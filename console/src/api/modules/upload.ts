import { getApiUrl, getApiToken } from "../config";

export interface UploadResponse {
  url: string;
  path: string;
  filename: string;
  size: number;
}

export const uploadApi = {
  uploadFile: async (file: File): Promise<UploadResponse> => {
    const formData = new FormData();
    formData.append("file", file);

    const headers: HeadersInit = {};
    const token = getApiToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    const response = await fetch(getApiUrl("/upload"), {
      method: "POST",
      headers,
      body: formData,
    });

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      throw new Error(
        `Upload failed: ${response.status} ${response.statusText}${text ? ` - ${text}` : ""}`,
      );
    }

    return response.json();
  },
};
