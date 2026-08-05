import type { DirectoryEntry } from "./types";

export interface MemoryTreeEntry extends DirectoryEntry {
  children?: MemoryTreeEntry[];
}

function modifiedTimestamp(value: string): number {
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
}

export function buildMemoryTree(files: DirectoryEntry[]): MemoryTreeEntry[] {
  const root: MemoryTreeEntry[] = [];

  files
    .filter((file) => file.path.toLowerCase().endsWith(".md"))
    .forEach((file) => {
      const parts = file.path.split("/").filter(Boolean);
      let entries = root;
      parts.forEach((part, index) => {
        const path = parts.slice(0, index + 1).join("/");
        const isFile = index === parts.length - 1;
        if (isFile) {
          entries.push({ ...file, name: part, path });
          return;
        }
        let directory = entries.find(
          (entry) => entry.kind === "directory" && entry.name === part,
        );
        if (!directory) {
          directory = {
            name: part,
            path,
            kind: "directory",
            size: null,
            modified_at: file.modified_at,
            preview_kind: "text",
            children: [],
          };
          entries.push(directory);
        } else if (
          modifiedTimestamp(file.modified_at) >
          modifiedTimestamp(directory.modified_at)
        ) {
          directory.modified_at = file.modified_at;
        }
        entries = directory.children ?? [];
      });
    });

  const sortEntries = (entries: MemoryTreeEntry[]) => {
    entries.sort((left, right) => {
      const modifiedDifference =
        modifiedTimestamp(right.modified_at) -
        modifiedTimestamp(left.modified_at);
      if (modifiedDifference !== 0) return modifiedDifference;
      if (left.kind !== right.kind) return left.kind === "directory" ? -1 : 1;
      return left.name.localeCompare(right.name, undefined, {
        numeric: true,
        sensitivity: "base",
      });
    });
    entries.forEach((entry) => {
      if (entry.children) sortEntries(entry.children);
    });
  };
  sortEntries(root);
  return root;
}
