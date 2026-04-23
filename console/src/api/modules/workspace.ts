import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import type { MdFileInfo, MdFileContent, DailyMemoryFile } from "../types";

function getSelectedAgentId(): string {
  try {
    const agentStorage = sessionStorage.getItem("qwenpaw-agent-storage");
    if (agentStorage) {
      const parsed = JSON.parse(agentStorage);
      const selectedAgent = parsed?.state?.selectedAgent;
      if (selectedAgent) {
        return selectedAgent;
      }
    }
  } catch (error) {
    console.warn("Failed to get selected agent from storage:", error);
  }
  return "default";
}

function generateFallbackFilename(): string {
  const agentId = getSelectedAgentId();
  const now = new Date();
  const timestamp = now
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\..+/, "")
    .replace("T", "_")
    .slice(0, 15); // YYYYMMDD_HHMMSS
  return `qwenpaw_workspace_${agentId}_${timestamp}.zip`;
}

export interface WorkspaceDownloadResult {
  blob: Blob;
  filename: string;
}

export const workspaceApi = {
  listFiles: () =>
    request<MdFileInfo[]>("/workspace/files").then((files) =>
      files.map((file) => ({
        ...file,
        updated_at: new Date(file.modified_time).getTime(),
      })),
    ),

  loadFile: (fileName: string) =>
    request<MdFileContent>(`/workspace/files/${encodeURIComponent(fileName)}`),

  saveFile: (fileName: string, content: string) =>
    request<Record<string, unknown>>(
      `/workspace/files/${encodeURIComponent(fileName)}`,
      {
        method: "PUT",
        body: JSON.stringify({ content }),
      },
    ),

  // Workspace package download
  downloadWorkspace: async (): Promise<WorkspaceDownloadResult> => {
    const response = await fetch(getApiUrl("/workspace/download"), {
      method: "GET",
      headers: buildAuthHeaders(),
    });

    if (!response.ok) {
      throw new Error(
        `Workspace download failed: ${response.status} ${response.statusText}`,
      );
    }

    const blob = await response.blob();

    // Extract filename from Content-Disposition header
    const disposition = response.headers.get("Content-Disposition");
    let filename: string;

    if (disposition) {
      const filenameMatch = disposition.match(/filename="(.+?)"/);
      if (filenameMatch && filenameMatch[1]) {
        filename = filenameMatch[1];
      } else {
        filename = generateFallbackFilename();
      }
    } else {
      filename = generateFallbackFilename();
    }

    return { blob, filename };
  },

  // File upload functionality
  uploadFile: async (
    file: File,
  ): Promise<{ success: boolean; message: string }> => {
    const formData = new FormData();
    formData.append("file", file);

    const response = await fetch(getApiUrl("/workspace/upload"), {
      method: "POST",
      headers: buildAuthHeaders(),
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `Upload failed: ${response.status} ${response.statusText} - ${errorText}`,
      );
    }

    return await response.json();
  },

  listDailyMemory: () =>
    request<MdFileInfo[]>("/workspace/memory").then((files) =>
      files.map((file) => {
        const date = file.filename.replace(".md", "");
        return {
          ...file,
          date,
          updated_at: new Date(file.modified_time).getTime(),
        } as DailyMemoryFile;
      }),
    ),

  loadDailyMemory: (date: string) =>
    request<MdFileContent>(`/workspace/memory/${encodeURIComponent(date)}.md`),

  saveDailyMemory: (date: string, content: string) =>
    request<Record<string, unknown>>(
      `/workspace/memory/${encodeURIComponent(date)}.md`,
      {
        method: "PUT",
        body: JSON.stringify({ content }),
      },
    ),

  // System prompt files management
  getSystemPromptFiles: () =>
    request<string[]>("/workspace/system-prompt-files"),

  setSystemPromptFiles: (files: string[]) =>
    request<string[]>("/workspace/system-prompt-files", {
      method: "PUT",
      body: JSON.stringify(files),
    }),
};
