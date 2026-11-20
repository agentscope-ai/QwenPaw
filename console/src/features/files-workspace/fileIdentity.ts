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

/** Decode persisted tabs even when optional source/root metadata is absent. */
export function fileTabTarget(tab: EditorTab): FileTarget {
  const separator = tab.path.indexOf("::");
  const prefix = separator < 0 ? "" : tab.path.slice(0, separator);
  return {
    source:
      tab.source ??
      (prefix === "memory" ||
      prefix === "daily" ||
      prefix === "digest" ||
      prefix === "profile" ||
      prefix === "attachment"
        ? prefix
        : "workspace"),
    path:
      tab.displayPath ??
      (separator < 0 ? tab.path : tab.path.slice(separator + 2)),
    root:
      tab.workspaceRoot ??
      (prefix === "workspace-root"
        ? "workspace"
        : prefix.startsWith("project:")
        ? (prefix as FileTarget["root"])
        : undefined),
    artifactUrl: tab.artifactUrl,
  };
}

/** Only agent workspace and memory sources can name the same storage file. */
export function workspacePath(
  target: FileTarget,
  memory: MemoryFileConfig | null,
) {
  if (target.artifactUrl) return null;
  if (target.source === "workspace")
    return target.root === "workspace" ? target.path : null;
  if (!memory) return null;
  let directory =
    target.source === "daily" || target.source === "memory"
      ? memory.daily_dir
      : target.source === "digest"
      ? memory.digest_dir
      : null;
  let path = target.path.replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");
  // Match AgentMdManager._normalize_md_path and legacy digest routing.
  if (
    !path ||
    path.split("/").some((part) => !part || part === "." || part === "..")
  )
    return null;
  if (!path.endsWith(".md")) path += ".md";
  const digestPrefix = memory.digest_dir
    .replace(/\\/g, "/")
    .split("/")
    .filter((part) => part && part !== ".")
    .pop();
  if (
    target.source === "memory" &&
    digestPrefix &&
    path.startsWith(`${digestPrefix}/`)
  ) {
    directory = memory.digest_dir;
    path = path.slice(digestPrefix.length + 1);
  }
  return directory === null
    ? null
    : `${directory}/${path}`
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
    return (
      tab.path === path ||
      (workspace !== null &&
        workspacePath(fileTabTarget(tab), memory) === workspace)
    );
  });
  return matches.find((tab) => tab.dirty) ?? matches[0];
}
