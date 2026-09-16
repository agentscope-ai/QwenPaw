import { Dropdown } from "antd";
import {
  ChevronLeft,
  ChevronRight,
  File,
  Folder,
  FolderOpen,
  LoaderCircle,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { workspaceApi } from "../../api/modules/workspace";
import type {
  DirectoryPage,
  WorkspaceRoot,
} from "../../features/files-workspace/types";
import styles from "./FileBreadcrumbs.module.less";

interface FileBreadcrumbsProps {
  path: string;
  root?: WorkspaceRoot;
  chatId?: string;
  projectDirOverride?: string;
  onOpenFile: (path: string, root: WorkspaceRoot) => void;
}

interface DirectoryState extends DirectoryPage {
  loadingMore?: boolean;
}

function parentPath(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/$/, "");
  const separator = normalized.lastIndexOf("/");
  return separator < 0 ? "" : normalized.slice(0, separator);
}

function basename(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/$/, "");
  return normalized.split("/").filter(Boolean).pop() ?? normalized;
}

export default function FileBreadcrumbs({
  path,
  root = "project",
  chatId,
  projectDirOverride,
  onOpenFile,
}: FileBreadcrumbsProps) {
  const { t } = useTranslation();
  const requestSequence = useRef(0);
  const [openDirectory, setOpenDirectory] = useState<string | null>(null);
  const [browsePath, setBrowsePath] = useState("");
  const [directories, setDirectories] = useState<
    Record<string, DirectoryState>
  >({});
  const [loadingPath, setLoadingPath] = useState<string | null>(null);
  const [failedPath, setFailedPath] = useState<string | null>(null);

  const normalizedPath = path.replace(/\\/g, "/");
  const segments = normalizedPath.split("/").filter(Boolean);
  const filename = segments.pop() ?? normalizedPath;
  const directoryCrumbs = [
    {
      label: t(
        root === "workspace" ? "files.workspace" : "files.projectDirectory",
      ),
      path: "",
    },
    ...segments.map((segment, index) => ({
      label: segment,
      path: segments.slice(0, index + 1).join("/"),
    })),
  ];

  useEffect(() => {
    setOpenDirectory(null);
  }, [normalizedPath]);

  useEffect(() => {
    requestSequence.current += 1;
    setOpenDirectory(null);
    setBrowsePath("");
    setDirectories({});
    setLoadingPath(null);
    setFailedPath(null);
  }, [chatId, projectDirOverride, root]);

  const loadDirectory = useCallback(
    async (directory: string, cursor?: string) => {
      const sequence = ++requestSequence.current;
      if (cursor) {
        setDirectories((current) => ({
          ...current,
          [directory]: {
            ...current[directory],
            loadingMore: true,
          },
        }));
      } else {
        setLoadingPath(directory);
        setFailedPath(null);
      }
      try {
        const page = await workspaceApi.listDirectory(
          directory,
          cursor,
          200,
          chatId,
          root,
          projectDirOverride,
        );
        if (sequence !== requestSequence.current) return;
        setDirectories((current) => ({
          ...current,
          [directory]: {
            ...page,
            entries: cursor
              ? [...(current[directory]?.entries ?? []), ...page.entries]
              : page.entries,
            loadingMore: false,
          },
        }));
      } catch {
        if (sequence === requestSequence.current) setFailedPath(directory);
      } finally {
        if (sequence === requestSequence.current) setLoadingPath(null);
      }
    },
    [chatId, projectDirOverride, root],
  );

  const showDirectory = useCallback(
    (directory: string) => {
      setBrowsePath(directory);
      if (!directories[directory]) void loadDirectory(directory);
    },
    [directories, loadDirectory],
  );

  const currentDirectory = directories[browsePath];

  return (
    <nav className={styles.breadcrumbs} aria-label={t("files.navigator")}>
      {directoryCrumbs.map((crumb) => (
        <span className={styles.crumbGroup} key={crumb.path || "__root__"}>
          <Dropdown
            menu={{ items: [] }}
            open={openDirectory === crumb.path}
            onOpenChange={(open) => {
              if (!open) {
                setOpenDirectory(null);
                return;
              }
              setOpenDirectory(crumb.path);
              showDirectory(crumb.path);
            }}
            placement="bottomLeft"
            popupRender={() => (
              <section
                className={styles.directoryMenu}
                aria-label={basename(browsePath) || crumb.label}
              >
                <header className={styles.directoryMenuHeader}>
                  {browsePath ? (
                    <button
                      type="button"
                      aria-label={t("common.back")}
                      onClick={() => showDirectory(parentPath(browsePath))}
                    >
                      <ChevronLeft size={14} />
                    </button>
                  ) : (
                    <FolderOpen size={15} />
                  )}
                  <strong>{basename(browsePath) || crumb.label}</strong>
                </header>
                <div className={styles.directoryMenuBody}>
                  {loadingPath === browsePath && !currentDirectory ? (
                    <div className={styles.directoryState}>
                      <LoaderCircle className={styles.spin} size={15} />
                      {t("common.loading")}
                    </div>
                  ) : failedPath === browsePath ? (
                    <button
                      type="button"
                      className={styles.retryButton}
                      onClick={() => void loadDirectory(browsePath)}
                    >
                      {t("common.retry")}
                    </button>
                  ) : currentDirectory?.entries.length ? (
                    currentDirectory.entries.map((entry) => (
                      <button
                        type="button"
                        className={styles.directoryEntry}
                        key={`${entry.kind}:${entry.path}`}
                        onClick={() => {
                          if (entry.kind === "directory") {
                            showDirectory(entry.path);
                            return;
                          }
                          setOpenDirectory(null);
                          onOpenFile(entry.path, root);
                        }}
                      >
                        {entry.kind === "directory" ? (
                          <Folder size={15} />
                        ) : (
                          <File size={15} />
                        )}
                        <span>{entry.name}</span>
                        {entry.kind === "directory" && (
                          <ChevronRight size={13} />
                        )}
                      </button>
                    ))
                  ) : (
                    <div className={styles.directoryState}>
                      {t("files.sourceEmpty")}
                    </div>
                  )}
                  {currentDirectory?.has_more && (
                    <button
                      type="button"
                      className={styles.loadMore}
                      disabled={currentDirectory.loadingMore}
                      onClick={() =>
                        void loadDirectory(
                          browsePath,
                          currentDirectory.next_cursor ?? undefined,
                        )
                      }
                    >
                      {currentDirectory.loadingMore
                        ? t("common.loading")
                        : t("files.loadMore")}
                    </button>
                  )}
                </div>
              </section>
            )}
          >
            <button type="button" className={styles.crumb}>
              {crumb.path ? null : <FolderOpen size={13} />}
              <span>{crumb.label}</span>
            </button>
          </Dropdown>
          <ChevronRight className={styles.separator} size={12} />
        </span>
      ))}
      <span className={styles.filename} title={normalizedPath}>
        {filename}
      </span>
    </nav>
  );
}
