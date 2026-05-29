/**
 * Cross-runtime file download helper for browser, legacy pywebview, and Tauri.
 * Callers provide the URL and fallback name; this module picks the save path.
 */
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

interface DownloadBlobResult {
  blob: Blob;
  filename: string;
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

type PyWebViewSaveFile = NonNullable<PyWebViewDownloadApi["save_file"]>;

/** Return the legacy desktop save bridge when the app is running in pywebview. */
function getPyWebViewApi(): PyWebViewDownloadApi | undefined {
  return window.pywebview?.api;
}

/** Extract a suggested filename from the server's Content-Disposition header. */
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

/** Trigger a normal browser download by clicking a temporary blob-backed link. */
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

/** Normalize suggested filenames for native save dialogs across platforms. */
function sanitizeSaveFilename(filename: string): string {
  // Use Windows-safe names for native dialogs so suggested filenames work
  // across both packaged desktop shells and all supported OS file systems.
  const sanitized = filename
    .replace(/[<>:"/\\|?*]/g, "_")
    .trim()
    .replace(/[. ]+$/g, "");
  return sanitized || "download";
}

/** Fetch the file contents and optionally honor the server-provided filename. */
async function fetchDownloadBlob(
  url: string,
  options: DownloadFileOptions,
): Promise<DownloadBlobResult> {
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

/** Save through the legacy pywebview bridge used by the old desktop package. */
async function downloadWithPyWebView(
  saveFile: PyWebViewSaveFile,
  url: string,
  filename: string,
  options: DownloadFileOptions,
): Promise<void> {
  const headers = options.headers ?? {};
  const saved =
    Object.keys(headers).length > 0
      ? await saveFile(url, filename, headers)
      : await saveFile(url, filename);
  if (!saved) {
    throw new DownloadCancelledError();
  }
}

/** Ask Tauri's native dialog plugin for the destination path. */
async function getTauriSavePath(filename: string): Promise<string> {
  const savePath = await save({
    defaultPath: filename,
  });
  // No path means the user cancelled the native save dialog; it is not an error.
  if (!savePath) {
    throw new DownloadCancelledError();
  }
  return savePath;
}

/** Save in Tauri using the native dialog and filesystem plugins. */
async function downloadWithTauri(
  url: string,
  filename: string,
  options: DownloadFileOptions,
): Promise<void> {
  const savePath = await getTauriSavePath(filename);
  const { blob } = await fetchDownloadBlob(url, options);
  // The Tauri fs plugin write path currently buffers the whole response.
  // Large exports should be revisited if a streaming write API is adopted.
  await writeFile(savePath, new Uint8Array(await blob.arrayBuffer()));
}

/** Save in a regular browser by fetching a blob and clicking a download link. */
async function downloadWithBrowser(
  url: string,
  filename: string,
  options: DownloadFileOptions,
): Promise<void> {
  const { blob, filename: responseFilename } = await fetchDownloadBlob(
    url,
    options,
  );
  triggerBrowserDownload(blob, responseFilename || filename);
}

/** Download a URL using the best available runtime path: pywebview, Tauri, or browser. */
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
  const pywebviewSaveFile = getPyWebViewApi()?.save_file;
  if (pywebviewSaveFile && isHttpExternalUrl(requestUrl)) {
    await downloadWithPyWebView(
      pywebviewSaveFile,
      requestUrl,
      safeFilename,
      options,
    );
    return;
  }

  if (isDesktopTauriRuntime()) {
    await downloadWithTauri(requestUrl, safeFilename, options);
    return;
  }

  await downloadWithBrowser(requestUrl, filename, options);
}
