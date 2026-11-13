/** Open raw HTML in a new browser context across browser and desktop shells. */
import { invoke } from "@tauri-apps/api/core";
import { buildAuthHeaders } from "../api/authHeaders";
import { workspaceApi } from "../api/modules/workspace";
import type { WorkspaceRoot } from "../features/files-workspace/types";
import { isDesktopTauriRuntime } from "./openExternalLink";
import { getPyWebViewApi } from "./pywebview";

interface OpenHtmlFileOptions {
  content: string;
  filePath: string;
  chatId?: string;
  projectDirOverride?: string;
  root?: WorkspaceRoot;
  workspaceBacked?: boolean;
}

function workspaceHeaders(
  chatId?: string,
  projectDirOverride?: string,
): Record<string, string> {
  return {
    ...buildAuthHeaders(),
    ...(chatId ? { "X-Chat-Id": chatId } : {}),
    ...(!chatId && projectDirOverride
      ? { "X-Session-Project-Dir": projectDirOverride }
      : {}),
  };
}

function openBlobHtml(content: string): void {
  const url = URL.createObjectURL(
    new Blob([content], { type: "text/html;charset=utf-8" }),
  );
  window.open(url, "_blank", "noopener,noreferrer");
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/** Which surface actually ended up showing the HTML. */
export type OpenHtmlFileMode = "native" | "blob";

export interface OpenHtmlFileResult {
  /** Whether the HTML ended up visible to the user. */
  opened: boolean;
  /**
   * ``native`` — the OS browser opened the real file (full fidelity).
   * ``blob`` — rendered from the in-memory copy, because the native shell
   * refused it (for example a file that lives outside the workspace).
   */
  mode: OpenHtmlFileMode;
}

function nativeResult(): OpenHtmlFileResult {
  return { opened: true, mode: "native" };
}

// The native shell only opens HTML that resolves *inside* the workspace; it
// answers `false` — not an error — for anything else. Render the copy we
// already hold instead of leaving the click a silent no-op.
function fallbackResult(content: string): OpenHtmlFileResult {
  openBlobHtml(content);
  return { opened: true, mode: "blob" };
}

export function openHtmlFile(
  options: OpenHtmlFileOptions,
): Promise<OpenHtmlFileResult> {
  const {
    content,
    filePath,
    chatId,
    projectDirOverride,
    root = "project",
    workspaceBacked = false,
  } = options;
  const resolverUrl = workspaceApi.getHtmlFileUriUrl(filePath, root);
  const headers = workspaceHeaders(chatId, projectDirOverride);
  const pywebviewApi = getPyWebViewApi();

  if (workspaceBacked && pywebviewApi?.open_workspace_html) {
    return pywebviewApi
      .open_workspace_html(resolverUrl, headers)
      .catch((error) => {
        console.warn("[html-preview] Native open failed", error);
        return false; // treat as declined → fall back below
      })
      .then((opened) => (opened ? nativeResult() : fallbackResult(content)));
  }

  if (workspaceBacked && isDesktopTauriRuntime()) {
    return invoke<boolean>("open_workspace_html", {
      url: resolverUrl,
      headers,
    })
      .catch((error) => {
        console.warn("[html-preview] Tauri open failed", error);
        return false; // treat as declined → fall back below
      })
      .then((opened) => (opened ? nativeResult() : fallbackResult(content)));
  }

  openBlobHtml(content);
  return Promise.resolve({ opened: true, mode: "blob" });
}
