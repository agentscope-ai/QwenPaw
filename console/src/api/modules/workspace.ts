import { request } from "../request";
import { getApiUrl } from "../config";
import { buildAuthHeaders } from "../authHeaders";
import { useCodeFileCacheStore } from "../../stores/codeFileCacheStore";
import { downloadFileFromUrl } from "../../utils/downloadFileFromUrl";
import type {
  MdFileInfo,
  MdFileContent,
  DailyMemoryFile,
  MemorySection,
} from "../types";
import type {
  DirectoryPage,
  FileMetadata,
  WorkspaceRoot,
} from "../../features/files-workspace/types";

function getSelectedAgentId(): string {
  try {
    // Read from sessionStorage first (per-tab agent), fall back to localStorage
    const agentStorage =
      sessionStorage.getItem("qwenpaw-agent-storage") ||
      localStorage.getItem("qwenpaw-agent-storage");
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

function encodePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

function workspaceQuery(
  path: string,
  values: Record<string, string | number | undefined>,
): string {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });
  return `${path}?${query.toString()}`;
}

function projectHeaders(
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

export class UploadConflictError extends Error {
  files: string[];

  constructor(files: string[]) {
    super("Upload contains conflicting filenames");
    this.name = "UploadConflictError";
    this.files = files;
  }
}

interface WorkspaceFileChunk {
  path: string;
  content: string;
  offset: number;
  limit: number;
  next_offset: number;
  eof: boolean;
  truncated: boolean;
  encoding: string;
  etag: string;
}

export const workspaceApi = {
  listDirectory: (
    path = "",
    cursor?: string,
    limit = 200,
    chatId?: string,
    root: WorkspaceRoot = "project",
    projectDirOverride?: string,
  ): Promise<DirectoryPage> =>
    request<DirectoryPage>(
      workspaceQuery("/workspace/tree", { path, cursor, limit, root }),
      { headers: projectHeaders(chatId, projectDirOverride) },
    ),

  getFileMetadata: (
    path: string,
    chatId?: string,
    root: WorkspaceRoot = "project",
    projectDirOverride?: string,
  ): Promise<FileMetadata> =>
    request<FileMetadata>(
      workspaceQuery("/workspace/file-metadata", { path, root }),
      { headers: projectHeaders(chatId, projectDirOverride) },
    ),

  loadFileChunk: (
    path: string,
    offset = 0,
    limit = 256 * 1024,
    chatId?: string,
    root: WorkspaceRoot = "project",
    projectDirOverride?: string,
  ): Promise<WorkspaceFileChunk> =>
    request<WorkspaceFileChunk>(
      workspaceQuery("/workspace/file-content", {
        path,
        offset,
        limit,
        root,
      }),
      { headers: projectHeaders(chatId, projectDirOverride) },
    ),

  loadFileText: async (
    path: string,
    chatId?: string,
    root: WorkspaceRoot = "project",
    projectDirOverride?: string,
  ): Promise<{ content: string; etag: string }> => {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const chunks: string[] = [];
      let offset = 0;
      let etag = "";
      let versionChanged = false;
      for (;;) {
        let chunk: WorkspaceFileChunk;
        try {
          chunk = await workspaceApi.loadFileChunk(
            path,
            offset,
            256 * 1024,
            chatId,
            root,
            projectDirOverride,
          );
        } catch (error) {
          if (attempt === 0) {
            versionChanged = true;
            break;
          }
          throw error;
        }
        if (!etag) {
          etag = chunk.etag;
        } else if (chunk.etag !== etag) {
          versionChanged = true;
          break;
        }
        chunks.push(chunk.content);
        if (chunk.eof) {
          return { content: chunks.join(""), etag };
        }
        if (chunk.next_offset <= offset) {
          throw new Error("Workspace file reader did not advance");
        }
        offset = chunk.next_offset;
      }
      if (!versionChanged || attempt === 1) {
        throw new Error("Workspace file changed while it was being read");
      }
    }
    throw new Error("Workspace file changed while it was being read");
  },

  saveFileContent: async (
    path: string,
    content: string,
    etag?: string,
    chatId?: string,
    root: WorkspaceRoot = "project",
    projectDirOverride?: string,
  ): Promise<{ path: string; size: number; etag: string }> => {
    const response = await fetch(
      getApiUrl(workspaceQuery("/workspace/file-content", { path, root })),
      {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          ...projectHeaders(chatId, projectDirOverride),
          ...(etag ? { "If-Match": etag } : {}),
        },
        body: JSON.stringify({ content }),
      },
    );
    if (!response.ok) {
      throw new Error(`Workspace save failed: ${response.status}`);
    }
    return response.json();
  },

  getFileDownloadUrl: (path: string, root: WorkspaceRoot = "project") =>
    getApiUrl(workspaceQuery("/workspace/file-download", { path, root })),

  getHtmlFileUriUrl: (path: string, root: WorkspaceRoot = "project") =>
    getApiUrl(workspaceQuery("/workspace/html-file-uri", { path, root })),

  uploadFiles: async (
    files: File[],
    path = "",
    conflict?: "overwrite" | "skip" | "rename",
    chatId?: string,
    root: WorkspaceRoot = "project",
    projectDirOverride?: string,
  ): Promise<{
    files: Array<{
      name: string;
      path: string;
      size?: number;
      status: "uploaded" | "skipped";
    }>;
  }> => {
    const formData = new FormData();
    files.forEach((file) => formData.append("files", file));
    const response = await fetch(
      getApiUrl(
        workspaceQuery("/workspace/file-upload", {
          path,
          conflict,
          root,
        }),
      ),
      {
        method: "POST",
        headers: projectHeaders(chatId, projectDirOverride),
        body: formData,
      },
    );
    if (response.status === 409) {
      const payload = await response.json().catch(() => null);
      if (payload?.detail?.code === "upload_conflict") {
        throw new UploadConflictError(
          Array.isArray(payload.detail.files) ? payload.detail.files : [],
        );
      }
    }
    if (!response.ok) {
      throw new Error(`File upload failed: ${response.status}`);
    }
    return response.json();
  },

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
  downloadWorkspace: () =>
    downloadFileFromUrl(
      getApiUrl("/workspace/download"),
      generateFallbackFilename(),
      {
        headers: buildAuthHeaders(),
        errorMessage: "Workspace download failed",
        preferResponseFilename: true,
      },
    ),

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

  listMemoryFiles: (section: MemorySection) =>
    request<MdFileInfo[]>(workspaceQuery("/workspace/memory", { section })),

  loadMemoryFile: (memoryPath: string, section: MemorySection) =>
    request<MdFileContent>(
      workspaceQuery(`/workspace/memory/${encodePath(memoryPath)}`, {
        section,
      }),
    ),

  saveMemoryFile: (
    memoryPath: string,
    content: string,
    section: MemorySection,
  ) =>
    request<Record<string, unknown>>(
      workspaceQuery(`/workspace/memory/${encodePath(memoryPath)}`, {
        section,
      }),
      {
        method: "PUT",
        body: JSON.stringify({ content }),
      },
    ),

  // Legacy helpers retained for persisted tabs and older callers.
  listDailyMemory: () =>
    request<MdFileInfo[]>("/workspace/memory").then((files) =>
      files.map((file) => {
        const basename = file.filename.split("/").pop() || file.filename;
        const date = basename.replace(".md", "");
        return {
          ...file,
          date,
          updated_at: new Date(file.modified_time).getTime(),
        } as DailyMemoryFile;
      }),
    ),

  loadDailyMemory: (memoryPath: string) =>
    request<MdFileContent>(`/workspace/memory/${encodePath(memoryPath)}`),

  saveDailyMemory: (memoryPath: string, content: string) =>
    request<Record<string, unknown>>(
      `/workspace/memory/${encodePath(memoryPath)}`,
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

  // Coding Mode – full file tree (all file types)
  listCodeFiles: () =>
    request<MdFileInfo[]>("/workspace/code-files").then((files) =>
      files.map((file) => ({
        ...file,
        updated_at: new Date(file.modified_time).getTime(),
      })),
    ),

  /**
   * Load a workspace file's text content.
   *
   * Cache strategy: returns the in-memory cached content immediately when
   * present (no network). Otherwise issues a GET with `If-None-Match` from
   * the cached ETag (if any) so a hard-refresh can short-circuit to 304.
   * Cache invalidation is driven by the shared workspace watcher.
   */
  loadCodeFile: async (
    filePath: string,
  ): Promise<{ path: string; content: string }> => {
    const cache = useCodeFileCacheStore.getState();
    const cached = cache.get(filePath);
    if (cached) {
      return { path: filePath, content: cached.content };
    }

    const url = getApiUrl(
      `/workspace/code-files/${filePath
        .split("/")
        .map(encodeURIComponent)
        .join("/")}`,
    );
    const headers = new Headers();
    for (const [k, v] of Object.entries(buildAuthHeaders())) {
      headers.set(k, v);
    }
    // The browser handles `If-None-Match` automatically from its HTTP cache;
    // we only need to populate the in-memory cache from the response.
    const response = await fetch(url, { headers });

    if (!response.ok) {
      const text = await response.text().catch(() => "");
      const err = new Error(text || `Request failed: ${response.status}`);
      (err as Error & { status?: number }).status = response.status;
      throw err;
    }

    const data = (await response.json()) as { path: string; content: string };
    const etag = response.headers.get("ETag");
    cache.set(filePath, data.content, etag);
    return data;
  },

  saveCodeFile: (filePath: string, content: string) =>
    request<{ path: string; size: number }>(
      `/workspace/code-files/${filePath
        .split("/")
        .map(encodeURIComponent)
        .join("/")}`,
      {
        method: "PUT",
        body: JSON.stringify({ content }),
      },
    ).then((result) => {
      // Local edit: drop the cached entry — next read will refetch with the
      // server's new ETag. Cheaper than threading content through here.
      useCodeFileCacheStore.getState().invalidate(filePath);
      return result;
    }),

  /** Returns the URL for the SSE file-watch stream (Coding Mode). */
  getWatchUrl: (root: WorkspaceRoot = "project") =>
    `${getApiUrl("/workspace/watch")}?root=${encodeURIComponent(root)}`,

  /**
   * Returns the URL for a binary file (image, PDF, CSV) preview.
   * The browser can use this URL directly in <img>, <embed>, or fetch().
   */
  getBinaryFileUrl: (filePath: string) =>
    getApiUrl(
      `/workspace/binary-files/${filePath
        .split("/")
        .map(encodeURIComponent)
        .join("/")}`,
    ),
};
