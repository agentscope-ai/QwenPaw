import {
  filesWorkspaceScopeKey,
  type FilesWorkspaceScope,
} from "../files-workspace/filesWorkspaceScope";

const PROJECT_DIRECTORY_CHANGED_EVENT =
  "qwenpaw:files-project-directory-changed";

interface ProjectDirectoryChangeOptions {
  /** Persistence confirms the existing selection without discarding edits. */
  preserveTabs?: boolean;
}

export function notifyProjectDirectoryChanged(
  scope: FilesWorkspaceScope,
  options: ProjectDirectoryChangeOptions = {},
): void {
  window.dispatchEvent(
    new CustomEvent(PROJECT_DIRECTORY_CHANGED_EVENT, {
      detail: { scopeKey: filesWorkspaceScopeKey(scope), ...options },
    }),
  );
}

export function listenForProjectDirectoryChanges(
  listener: (scopeKey: string, options: ProjectDirectoryChangeOptions) => void,
): () => void {
  const handleChange = (event: Event) => {
    const detail = (
      event as CustomEvent<{ scopeKey: string } & ProjectDirectoryChangeOptions>
    ).detail;
    if (detail?.scopeKey) {
      listener(detail.scopeKey, { preserveTabs: detail.preserveTabs === true });
    }
  };
  window.addEventListener(PROJECT_DIRECTORY_CHANGED_EVENT, handleChange);
  return () =>
    window.removeEventListener(PROJECT_DIRECTORY_CHANGED_EVENT, handleChange);
}
