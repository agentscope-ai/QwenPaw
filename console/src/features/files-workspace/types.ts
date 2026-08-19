export type FileSource =
  | "workspace"
  | "attachment"
  | "profile"
  | "memory"
  | "daily"
  | "digest";
export type WorkspaceRoot = "project" | "workspace";
export type MemoryGraphRoot = "wiki" | "procedure" | "personal";

export interface FileTarget {
  source: FileSource;
  path: string;
  root?: WorkspaceRoot;
  /** Stable URL emitted by a chat tool result for a historical artifact. */
  artifactUrl?: string;
  line?: number;
  endLine?: number;
  column?: number;
}

export type FilesDrawerState =
  | { kind: "closed" }
  | { kind: "preview"; target: FileTarget; trigger: HTMLElement | null }
  | {
      kind: "workspace";
      target?: FileTarget;
      trigger: HTMLElement | null;
    };

export type FilesDrawerEvent =
  | {
      type: "OPEN_PREVIEW";
      target: FileTarget;
      trigger: HTMLElement | null;
    }
  | {
      type: "OPEN_WORKSPACE";
      target?: FileTarget;
      trigger: HTMLElement | null;
    }
  | { type: "EXPAND_WORKSPACE" }
  | { type: "COLLAPSE_TO_PREVIEW" }
  | { type: "CLOSE" };

export interface FileMetadata {
  path: string;
  size: number;
  modified_at: string;
  preview_kind: "text" | "image" | "pdf" | "csv" | "binary";
  etag: string;
}

export interface DirectoryEntry {
  name: string;
  path: string;
  kind: "file" | "directory";
  size: number | null;
  modified_at: string;
  preview_kind: string;
}

export interface DirectoryPage {
  directory: string;
  entries: DirectoryEntry[];
  next_cursor: string | null;
  has_more: boolean;
}
