import {
  filesWorkspaceScopeKey,
  type FilesWorkspaceScope,
} from "../files-workspace/filesWorkspaceScope";

const PROJECT_DIRECTORY_CHANGED_EVENT =
  "qwenpaw:files-project-directory-changed";

export function notifyProjectDirectoryChanged(
  scope: FilesWorkspaceScope,
): void {
  window.dispatchEvent(
    new CustomEvent(PROJECT_DIRECTORY_CHANGED_EVENT, {
      detail: { scopeKey: filesWorkspaceScopeKey(scope) },
    }),
  );
}

export function listenForProjectDirectoryChanges(
  listener: (scopeKey: string) => void,
): () => void {
  const handleChange = (event: Event) => {
    const detail = (event as CustomEvent<{ scopeKey: string }>).detail;
    if (detail?.scopeKey) listener(detail.scopeKey);
  };
  window.addEventListener(PROJECT_DIRECTORY_CHANGED_EVENT, handleChange);
  return () =>
    window.removeEventListener(PROJECT_DIRECTORY_CHANGED_EVENT, handleChange);
}
