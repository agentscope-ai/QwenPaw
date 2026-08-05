import type { MdFileInfo } from "../../api/types";
import { splitFileReferences } from "./fileReferenceFormatting";

export interface WorkspacePathMentionItem {
  value: string;
  label: string;
  type: "file" | "folder";
}

export function buildWorkspacePathMentionItems(
  files: MdFileInfo[],
): WorkspacePathMentionItem[] {
  const filePaths = new Set<string>();
  const folderPaths = new Set<string>();

  for (const file of files) {
    const path = (file.path || file.filename).replace(/^\/+|\/+$/g, "");
    if (!path) continue;

    filePaths.add(path);
    const parts = path.split("/");
    for (let index = 1; index < parts.length; index += 1) {
      folderPaths.add(parts.slice(0, index).join("/"));
    }
  }

  const byPath = (left: string, right: string) =>
    left.localeCompare(right, undefined, {
      numeric: true,
      sensitivity: "base",
    });

  return [
    ...Array.from(folderPaths)
      .sort(byPath)
      .map((path) => ({
        value: path,
        label: path,
        type: "folder" as const,
      })),
    ...Array.from(filePaths)
      .sort(byPath)
      .map((path) => ({
        value: path,
        label: path,
        type: "file" as const,
      })),
  ];
}

export function formatWorkspacePathMention(
  item: Pick<WorkspacePathMentionItem, "value"> & { type?: string },
): string {
  const path =
    item.type === "folder" && !/[\\/]$/.test(item.value)
      ? `${item.value}/`
      : item.value;
  const serializedPath = /\s|"/.test(path) ? JSON.stringify(path) : path;
  return `@ ${serializedPath}`;
}

export function extractWorkspacePathMentions(value: string) {
  return splitFileReferences(value).flatMap((segment) => {
    const reference = segment.reference;
    if (!segment.text.startsWith("@ ") || !reference) return [];
    if (reference.kind !== "file" && reference.kind !== "folder") return [];
    return [{ value: reference.path, type: reference.kind }];
  });
}
