import type { WorkspaceRoot } from "./types";

export function normalizeDirectoryPath(path: string): string {
  const normalized = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  return /^[a-z]:\//i.test(normalized) ? normalized.toLowerCase() : normalized;
}

export function directoriesMatch(
  projectDirectory: string,
  workspaceDirectory: string,
): boolean {
  return (
    Boolean(projectDirectory) &&
    normalizeDirectoryPath(projectDirectory) ===
      normalizeDirectoryPath(workspaceDirectory)
  );
}

export function workspaceRoots(sameDirectory: boolean): WorkspaceRoot[] {
  return sameDirectory ? ["workspace"] : ["project", "workspace"];
}
