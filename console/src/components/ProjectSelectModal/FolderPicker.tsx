/**
 * FolderPicker – interactive server-side directory browser.
 *
 * Displays a breadcrumb path + scrollable directory list backed by
 * GET /workspace/coding-project/browse.
 * The user navigates into subdirectories and clicks "Select" to confirm.
 */

import { useCallback, useEffect, useState } from "react";
import { Button, Spin, Tooltip } from "antd";
import { ChevronRight, Folder, GitBranch, ArrowLeft } from "lucide-react";
import { codingProjectApi, type FsBrowseResult } from "../../api/modules/codingProject";
import styles from "./FolderPicker.module.less";

interface FolderPickerProps {
  /** Called with the selected absolute path when user clicks "Select". */
  onSelect: (path: string) => void;
  /** Initial path to open (defaults to "~"). */
  initialPath?: string;
}

// ---------------------------------------------------------------------------
// Breadcrumb helpers
// ---------------------------------------------------------------------------

function pathParts(p: string): { label: string; path: string }[] {
  if (!p || p === "/") return [{ label: "/", path: "/" }];
  const parts = p.split("/").filter(Boolean);
  return [
    { label: "/", path: "/" },
    ...parts.map((part, i) => ({
      label: part,
      path: "/" + parts.slice(0, i + 1).join("/"),
    })),
  ];
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function FolderPicker({ onSelect, initialPath = "~" }: FolderPickerProps) {
  const [current, setCurrent] = useState<FsBrowseResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const navigate = useCallback(async (path: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await codingProjectApi.browse(path);
      setCurrent(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to browse directory");
    } finally {
      setLoading(false);
    }
  }, []);

  // Load initial path on mount
  useEffect(() => {
    void navigate(initialPath);
  }, [initialPath, navigate]);

  const crumbs = current ? pathParts(current.path) : [];

  return (
    <div className={styles.picker}>
      {/* Breadcrumb navigation */}
      <div className={styles.breadcrumb}>
        {current?.parent && (
          <button
            type="button"
            className={styles.upBtn}
            onClick={() => void navigate(current.parent!)}
            title="Go up"
          >
            <ArrowLeft size={13} />
          </button>
        )}
        <div className={styles.crumbs}>
          {crumbs.map((crumb, i) => (
            <span key={crumb.path} className={styles.crumbWrap}>
              {i > 0 && <ChevronRight size={10} className={styles.crumbSep} />}
              <button
                type="button"
                className={styles.crumb}
                onClick={() => void navigate(crumb.path)}
              >
                {crumb.label}
              </button>
            </span>
          ))}
        </div>
      </div>

      {/* Current path display */}
      {current && (
        <div className={styles.currentPath}>
          <code>{current.path}</code>
        </div>
      )}

      {/* Directory listing */}
      <div className={styles.list}>
        {loading && !current && <Spin size="small" className={styles.spin} />}
        {error && <div className={styles.error}>{error}</div>}
        {current?.entries.map((entry) => (
          <button
            key={entry.name}
            type="button"
            className={`${styles.entry} ${!entry.is_dir ? styles.entryFile : ""}`}
            onClick={() => entry.is_dir && void navigate(`${current.path}/${entry.name}`)}
            disabled={!entry.is_dir}
            title={entry.name}
          >
            <span className={styles.entryIcon}>
              {entry.is_git ? (
                <GitBranch size={13} className={styles.gitIcon} />
              ) : (
                <Folder size={13} />
              )}
            </span>
            <span className={styles.entryName}>{entry.name}</span>
            {entry.is_git && <span className={styles.gitBadge}>git</span>}
            {entry.is_dir && <ChevronRight size={11} className={styles.entryArrow} />}
          </button>
        ))}
        {current && current.entries.filter((e) => e.is_dir).length === 0 && (
          <div className={styles.empty}>No subdirectories</div>
        )}
      </div>

      {/* Action bar */}
      <div className={styles.actions}>
        <Tooltip title={current?.path}>
          <span className={styles.selectedLabel}>
            {current ? current.path.split("/").pop() || "/" : "—"}
          </span>
        </Tooltip>
        <Button
          type="primary"
          size="small"
          disabled={!current}
          onClick={() => current && onSelect(current.path)}
        >
          Select This Folder
        </Button>
      </div>
    </div>
  );
}
