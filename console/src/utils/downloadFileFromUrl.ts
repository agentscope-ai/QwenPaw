/**
 * Cross-runtime file download helper for browser, legacy pywebview, and Tauri.
 * Callers provide the URL and fallback name; this module picks the save path.
 */
import { save } from "@tauri-apps/plugin-dialog";
import { invoke } from "@tauri-apps/api/core";
import { download as tauriDownload } from "@tauri-apps/plugin-upload";
import {
  isDesktopTauriRuntime,
  isHttpExternalUrl,
  resolveExternalUrl,
} from "./openExternalLink";
import { getPyWebViewApi, type PyWebViewSaveFile } from "./pywebview";

export interface DownloadFileOptions {
  headers?: Record<string, string>;
  errorMessage?: string;
  /**
   * Prefer Content-Disposition filenames when the browser path fetches the file.
   * Native desktop paths use the fallback filename shown in the save dialog.
   */
  preferResponseFilename?: boolean;
}

export class DownloadCancelledError extends Error {
  constructor() {
    super("Download cancelled");
    this.name = "DownloadCancelledError";
  }
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
  setTimeout(() => {
    URL.revokeObjectURL(objectUrl);
    a.remove();
  }, 0);
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

/** Keep headers as plain IPC objects; Tauri deserializes them into Rust HashMap. */
function headersForTauri(
  headers?: Record<string, string>,
): Parameters<typeof tauriDownload>[3] {
  const entries = Object.entries(headers ?? {});
  return entries.length > 0
    ? (Object.fromEntries(entries) as unknown as Parameters<
        typeof tauriDownload
      >[3])
    : undefined;
}

function errorMessageForLog(error: unknown): string {
  if (error instanceof Error) {
    const cause = (error as Error & { cause?: unknown }).cause;
    return cause ? `${error.message}; cause=${String(cause)}` : error.message;
  }
  return String(error);
}

function headerKeysForLog(headers?: Record<string, string>): string {
  return Object.keys(headers ?? {})
    .sort()
    .join(",");
}

async function logTauriDownloadEvent(
  stage: string,
  url: string,
  filename: string,
  detail?: string,
): Promise<void> {
  if (!isDesktopTauriRuntime()) return;
  try {
    await invoke("log_download_event", {
      context: {
        runtime: "tauri",
        stage,
        url,
        filename,
        detail,
      },
    });
  } catch {
    // Diagnostic logging must not change the download behavior.
  }
}

async function logTauriDownloadFailure(
  url: string,
  filename: string,
  error: unknown,
): Promise<void> {
  try {
    await invoke("log_download_failure", {
      context: {
        runtime: "tauri",
        url,
        filename,
        error: errorMessageForLog(error),
      },
    });
  } catch {
    // Diagnostic logging must not mask the original download error.
  }
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
  await logTauriDownloadEvent("save-dialog-open", "", filename);
  const savePath = await save({
    defaultPath: filename,
  });
  // No path means the user cancelled the native save dialog; it is not an error.
  if (!savePath) {
    await logTauriDownloadEvent("save-dialog-cancelled", "", filename);
    throw new DownloadCancelledError();
  }
  await logTauriDownloadEvent("save-dialog-selected", "", filename);
  return savePath;
}

/** Save in Tauri with a native dialog and Rust-side streaming download. */
async function downloadWithTauri(
  url: string,
  filename: string,
  options: DownloadFileOptions,
): Promise<void> {
  let savePath: string;
  try {
    savePath = await getTauriSavePath(filename);
  } catch (error) {
    if (!(error instanceof DownloadCancelledError)) {
      await logTauriDownloadFailure(url, filename, error);
      await logTauriDownloadEvent(
        "save-dialog-error",
        url,
        filename,
        errorMessageForLog(error),
      );
    }
    throw error;
  }

  await logTauriDownloadEvent(
    "tauri-download-start",
    url,
    filename,
    `headerKeys=${headerKeysForLog(options.headers)}`,
  );
  try {
    await tauriDownload(
      url,
      savePath,
      undefined,
      headersForTauri(options.headers),
    );
    await logTauriDownloadEvent("tauri-download-success", url, filename);
  } catch (error) {
    await logTauriDownloadFailure(url, filename, error);
    if (options.errorMessage) {
      const wrappedError = new Error(options.errorMessage) as Error & {
        cause?: unknown;
      };
      wrappedError.cause = error;
      throw wrappedError;
    }
    throw error;
  }
}

/** Save in a regular browser by fetching a blob and clicking a download link. */
async function downloadWithBrowser(
  url: string,
  filename: string,
  options: DownloadFileOptions,
): Promise<void> {
  const res = await fetch(url, { headers: options.headers });
  if (!res.ok) {
    const error = new Error(
      options.errorMessage || `Download failed: ${res.status}`,
    ) as Error & { status?: number };
    error.status = res.status;
    throw error;
  }

  const responseFilename = options.preferResponseFilename
    ? filenameFromContentDisposition(res.headers.get("Content-Disposition"))
    : "";
  triggerBrowserDownload(
    await res.blob(),
    responseFilename ? sanitizeSaveFilename(responseFilename) : filename,
  );
}

/** Download a URL using the best available runtime path: pywebview, Tauri, or browser. */
export async function downloadFileFromUrl(
  url: string,
  filename: string,
  options: DownloadFileOptions = {},
): Promise<void> {
  await logTauriDownloadEvent(
    "entry",
    url,
    filename,
    `headerKeys=${headerKeysForLog(options.headers)}`,
  );
  if (!url) {
    throw new Error(options.errorMessage || "Download URL is empty");
  }

  const requestUrl = resolveExternalUrl(url);
  await logTauriDownloadEvent("resolved", requestUrl ?? "", filename);
  if (!requestUrl || !isHttpExternalUrl(requestUrl)) {
    await logTauriDownloadEvent("invalid-url", requestUrl ?? url, filename);
    throw new Error(options.errorMessage || "Download URL is invalid");
  }

  const safeFilename = sanitizeSaveFilename(filename);
  const pywebviewSaveFile = getPyWebViewApi()?.save_file;
  if (pywebviewSaveFile && isHttpExternalUrl(requestUrl)) {
    await logTauriDownloadEvent("runtime-pywebview", requestUrl, safeFilename);
    await downloadWithPyWebView(
      pywebviewSaveFile,
      requestUrl,
      safeFilename,
      options,
    );
    return;
  }

  if (isDesktopTauriRuntime()) {
    await logTauriDownloadEvent("runtime-tauri", requestUrl, safeFilename);
    await downloadWithTauri(requestUrl, safeFilename, options);
    return;
  }

  await logTauriDownloadEvent("runtime-browser", requestUrl, safeFilename);
  await downloadWithBrowser(requestUrl, safeFilename, options);
}
