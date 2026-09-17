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

export function openHtmlFile(options: OpenHtmlFileOptions): void {
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
    void pywebviewApi
      .open_workspace_html(resolverUrl, headers)
      .catch((error) =>
        console.warn("[html-preview] Native open failed", error),
      );
    return;
  }

  if (workspaceBacked && isDesktopTauriRuntime()) {
    void invoke("open_workspace_html", { url: resolverUrl, headers }).catch(
      (error) => console.warn("[html-preview] Tauri open failed", error),
    );
    return;
  }

  openBlobHtml(content);
}
