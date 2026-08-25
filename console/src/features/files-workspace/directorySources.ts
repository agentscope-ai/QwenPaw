import type { WorkspaceRoot } from "./types";

/**
 * Prefix addressing a non-primary bound project directory by path.
 *
 * Stays a path rather than an opaque id: the backend resolves it by
 * filesystem identity, and a persisted editor tab holds this token, so an id
 * that changed across a remount would orphan the tab it names.
 */
const EXTRA_PROJECT_ROOT_PREFIX = "project:";

/** Minimal shape of a bound directory; `ProjectDirEntry` satisfies it. */
export interface BoundDirLike {
  path: string;
  /**
   * Whether this entry is the agent workspace, as decided by the server.
   *
   * The client used to answer this by comparing `entry.path` against the
   * workspace path with a case fold chosen from the server's platform. That
   * is wrong in both directions — on a case-sensitive volume it merged two
   * real directories, and not folding merged nothing on a volume that folds —
   * and the symptom was one directory appearing as two switcher roots with
   * two sets of editor tabs. The server compares inodes instead.
   */
  is_workspace?: boolean;
}

/** Whether a root points at a project directory rather than the workspace. */
export function isProjectRoot(root: WorkspaceRoot | undefined): boolean {
  return (
    root === undefined ||
    root === "project" ||
    root.startsWith(EXTRA_PROJECT_ROOT_PREFIX)
  );
}

/**
 * The directory a root names, or null when it does not carry one.
 *
 * Null for both `"workspace"` and `"project"`: the primary is addressed by
 * name, so its path is only known from the bound list.
 */
export function projectRootPath(root: WorkspaceRoot): string | null {
  return root.startsWith(EXTRA_PROJECT_ROOT_PREFIX)
    ? root.slice(EXTRA_PROJECT_ROOT_PREFIX.length)
    : null;
}

/** Name the root for one bound directory. */
export function projectRootFor(
  path: string,
  isPrimary: boolean,
): WorkspaceRoot {
  return isPrimary ? "project" : `${EXTRA_PROJECT_ROOT_PREFIX}${path}`;
}

/**
 * The roots the navigator offers, in display order: one per bound directory
 * followed by the agent workspace.
 *
 * A bound directory that *is* the workspace collapses onto `"workspace"`
 * rather than getting a project root of its own — one directory addressable
 * two ways would show up twice in the switcher and split its editor tabs.
 * That also preserves the previous behaviour for an unbound session, whose
 * single synthesized entry is the workspace itself.
 *
 * An empty `dirs` means the directory list has not been fetched yet — never
 * "the workspace is the only root". Returning `["workspace"]` there would let
 * a caller reconciling its current root against this list conclude, during the
 * first render, that the project root does not exist and switch away from it.
 */
export function workspaceRoots(dirs: readonly BoundDirLike[]): WorkspaceRoot[] {
  if (dirs.length === 0) return [];
  const roots: WorkspaceRoot[] = [];
  dirs.forEach((entry, index) => {
    if (!entry.path) return;
    const root: WorkspaceRoot = entry.is_workspace
      ? "workspace"
      : projectRootFor(entry.path, index === 0);
    if (!roots.includes(root)) roots.push(root);
  });
  if (!roots.includes("workspace")) roots.push("workspace");
  return roots;
}
