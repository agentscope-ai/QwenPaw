import type { MarkdownFile } from "../../../../api/types";

export const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

export const formatTimeAgo = (time: number | string | undefined): string => {
  if (!time) return "unknown time";
  const timestamp = typeof time === "string" ? new Date(time).getTime() : time;
  if (isNaN(timestamp)) return "unknown time";
  const seconds = Math.floor((Date.now() - timestamp) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
};

export const isDailyMemoryFile = (filename: string): boolean => {
  return /^\d{4}-\d{2}-\d{2}\.md$/.test(filename);
};

export interface FileTreeNode {
  name: string;
  /** Dot-separated path from root e.g. "notes.daily" */
  id: string;
  files: MarkdownFile[];
  children: FileTreeNode[];
}

/**
 * Build a hierarchical tree from a flat list of files.
 * Uses file.path relative to workspacePath to derive folder structure.
 */
export const buildFileTree = (
  files: MarkdownFile[],
  workspacePath: string | null,
): FileTreeNode => {
  const root: FileTreeNode = { name: "", id: "_root_", files: [], children: [] };

  for (const file of files) {
    // Attempt to derive relative path segments
    let relPath = file.filename;
    if (workspacePath && file.path) {
      // Normalize separators to forward slash
      const normBase = workspacePath.replace(/\\/g, "/").replace(/\/?$/, "/");
      const normFull = file.path.replace(/\\/g, "/");
      if (normFull.startsWith(normBase)) {
        relPath = normFull.slice(normBase.length);
      }
    }

    const segments = relPath.split("/").filter(Boolean);

    if (segments.length <= 1) {
      // Root-level file
      root.files.push(file);
    } else {
      // File inside subdirectory — walk/create folder nodes
      let current = root;
      for (let i = 0; i < segments.length - 1; i++) {
        const seg = segments[i];
        const childId =
          current.id === "_root_" ? seg : `${current.id}.${seg}`;
        let child = current.children.find((c) => c.name === seg);
        if (!child) {
          child = { name: seg, id: childId, files: [], children: [] };
          current.children.push(child);
        }
        current = child;
      }
      current.files.push(file);
    }
  }

  return root;
};

