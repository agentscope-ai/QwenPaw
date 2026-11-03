import { isDefaultWorkspaceMarkdown } from "./defaultWorkspaceMarkdown";
import type { DirectoryEntry } from "./types";

export function selectProfileFiles(
  files: readonly DirectoryEntry[],
  enabledFiles: readonly string[],
): DirectoryEntry[] {
  const enabledOrder = new Map(
    enabledFiles.map((filename, index) => [filename, index]),
  );

  return files
    .filter(
      (file) =>
        isDefaultWorkspaceMarkdown(file.path) || enabledOrder.has(file.path),
    )
    .sort((left, right) => {
      const leftIndex = enabledOrder.get(left.path);
      const rightIndex = enabledOrder.get(right.path);
      if (leftIndex !== undefined && rightIndex !== undefined) {
        return leftIndex - rightIndex;
      }
      if (leftIndex !== undefined) return -1;
      if (rightIndex !== undefined) return 1;
      return left.name.localeCompare(right.name);
    });
}
