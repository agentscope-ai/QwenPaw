import { save } from "@tauri-apps/plugin-dialog";
import { writeFile } from "@tauri-apps/plugin-fs";
import {
  isDesktopTauriRuntime,
  isHttpExternalUrl,
  resolveExternalUrl,
} from "./openExternalLink";

export interface DownloadFileOptions {
  headers?: Record<string, string>;
  errorMessage?: string;
  preferResponseFilename?: boolean;
}

export class DownloadCancelledError extends Error {
  constructor() {
    super("Download cancelled");
    this.name = "DownloadCancelledError";
  }
}

interface PyWebViewDownloadApi {
  save_file?: (
    url: string,
    filename: string,
    headers?: Record<string, string>,
  ) => Promise<boolean>;
}

function getPyWebViewApi(): PyWebViewDownloadApi | undefined {
  return window.pywebview?.api;
}

function filenameFromContentDisposition(value: string | null): string {
  if (!value) return "";

  const utf8Match = value.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }

  const quotedMatch = value.match(/filename="([^"]+)"/i);
  if (quotedMatch?.[1]) {
    return quotedMatch[1];
  }

  const bareMatch = value.match(/filename=([^;]+)/i);
  return bareMatch?.[1]?.trim() ?? "";
}

function triggerBrowserDownload(blob: Blob, filename: string): void {
  const a = document.createElement("a");
  const objectUrl = URL.createObjectURL(blob);
  a.href = objectUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
  document.body.removeChild(a);
}

function sanitizeSaveFilename(filename: string): string {
  // Use Windows-safe names for native dialogs so suggested filenames work
  // across both packaged desktop shells and all supported OS file systems.
  const sanitized = filename
    .replace(/[<>:"/\\|?*]/g, "_")
    .trim()
    .replace(/[. ]+$/g, "");
  return sanitized || "download";
}

async function fetchDownloadBlob(
  url: string,
  options: DownloadFileOptions,
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch(url, { headers: options.headers });
  if (!res.ok) {
    const error = new Error(
      options.errorMessage || `Download failed: ${res.status}`,
    ) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }

  const filename = options.preferResponseFilename
    ? filenameFromContentDisposition(res.headers.get("Content-Disposition"))
    : "";
  return { blob: await res.blob(), filename };
}

export async function downloadFileFromUrl(
  url: string,
  filename: string,
  options: DownloadFileOptions = {},
): Promise<void> {
  if (!url) {
    throw new Error(options.errorMessage || "Download URL is empty");
  }

  const requestUrl = resolveExternalUrl(url);
  if (!requestUrl) {
    throw new Error(options.errorMessage || "Download URL is invalid");
  }

  const safeFilename = sanitizeSaveFilename(filename);
  const pywebviewApi = getPyWebViewApi();
  if (pywebviewApi?.save_file && isHttpExternalUrl(requestUrl)) {
    const headers = options.headers ?? {};
    const saved =
      Object.keys(headers).length > 0
        ? await pywebviewApi.save_file(requestUrl, safeFilename, headers)
        : await pywebviewApi.save_file(requestUrl, safeFilename);
    if (!saved) {
      throw new DownloadCancelledError();
    }
    return;
  }

  if (isDesktopTauriRuntime()) {
    const savePath = await save({
      defaultPath: safeFilename,
    });
    // No path means the user cancelled the native save dialog; it is not an error.
    if (!savePath) {
      throw new DownloadCancelledError();
    }

    const { blob } = await fetchDownloadBlob(requestUrl, options);
    // The Tauri fs plugin write path currently buffers the whole response.
    // Large exports should be revisited if a streaming write API is adopted.
    await writeFile(savePath, new Uint8Array(await blob.arrayBuffer()));
    return;
  }

  const { blob, filename: responseFilename } = await fetchDownloadBlob(
    requestUrl,
    options,
  );
  triggerBrowserDownload(blob, responseFilename || filename);
}
