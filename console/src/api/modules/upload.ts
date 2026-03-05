import { getApiUrl, getApiToken } from "../config";

export interface UploadResponse {
  url: string;
  filename: string;
  size: number;
}

export const uploadApi = {
  uploadFile: (
    file: File,
    onProgress?: (percent: number) => void,
  ): Promise<UploadResponse> => {
    return new Promise((resolve, reject) => {
      const formData = new FormData();
      formData.append("file", file);

      const xhr = new XMLHttpRequest();
      xhr.open("POST", getApiUrl("/upload"));

      const token = getApiToken();
      if (token) {
        xhr.setRequestHeader("Authorization", `Bearer ${token}`);
      }

      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      });

      xhr.addEventListener("load", () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            reject(new Error("Invalid JSON response"));
          }
        } else {
          reject(
            new Error(
              `Upload failed: ${xhr.status} ${xhr.statusText} - ${xhr.responseText}`,
            ),
          );
        }
      });

      xhr.addEventListener("error", () =>
        reject(new Error("Network error during upload")),
      );
      xhr.addEventListener("abort", () => reject(new Error("Upload aborted")));

      xhr.send(formData);
    });
  },
};
