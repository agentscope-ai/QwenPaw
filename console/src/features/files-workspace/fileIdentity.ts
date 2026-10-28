import type { EditorTab } from "../../stores/codingTabsStore";
import type { FileTarget } from "./types";
import type { MemoryFileConfig } from "./useMemoryTagSupport";

export function fileTabPath(target: FileTarget): string {
  if (target.source !== "workspace") return `${target.source}::${target.path}`;
  if (target.root === "workspace") return `workspace-root::${target.path}`;
  if (target.root && target.root !== "project")
    return `${target.root}::${target.path}`;
  return target.path;
}

/** Only agent workspace and memory sources can name the same storage file. */
function workspacePath(target: FileTarget, memory: MemoryFileConfig | null) {
  if (target.artifactUrl) return null;
  if (target.source === "workspace")
    return target.root === "workspace" ? target.path : null;
  if (!memory) return null;
  const directory =
    target.source === "daily" || target.source === "memory"
      ? memory.daily_dir
      : target.source === "digest"
      ? memory.digest_dir
      : null;
  return directory === null
    ? null
    : `${directory}/${target.path}`
        .replace(/\\/g, "/")
        .split("/")
        .filter((part) => part && part !== ".")
        .join("/");
}

export function findOpenFileTab(
  tabs: EditorTab[],
  target: FileTarget,
  memory: MemoryFileConfig | null,
) {
  const path = fileTabPath(target);
  const workspace = workspacePath(target, memory);
  const matches = tabs.filter((tab) => {
    const separator = tab.path.indexOf("::");
    const prefix = separator < 0 ? "" : tab.path.slice(0, separator);
    const source =
      tab.source ??
      (prefix === "memory" || prefix === "daily" || prefix === "digest"
        ? prefix
        : "workspace");
    return (
      tab.path === path ||
      (workspace !== null &&
        workspacePath(
          {
            source,
            path:
              tab.displayPath ??
              (separator < 0 ? tab.path : tab.path.slice(separator + 2)),
            root:
              tab.workspaceRoot ??
              (prefix === "workspace-root" ? "workspace" : undefined),
            artifactUrl: tab.artifactUrl,
          },
          memory,
        ) === workspace)
    );
  });
  return matches.find((tab) => tab.dirty) ?? matches[0];
}
