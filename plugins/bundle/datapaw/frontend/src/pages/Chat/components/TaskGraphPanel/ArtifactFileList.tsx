import { useTranslation } from "react-i18next";
import type { ArtifactFileLike } from "./artifactFileActions";
import drawerStyles from "./TaskNodeDrawer.module.less";

export type ArtifactFileListItem = ArtifactFileLike & { _nodeName?: string };

export interface ArtifactFileListProps {
  type: string;
  files: ArtifactFileListItem[];
  onPreview: (file: ArtifactFileListItem) => void;
  onDownload: (file: ArtifactFileListItem) => void;
  emptyText?: string;
}

/**
 * 与 TaskNodeDrawer「文件」Tab 相同的文件列表展示与操作按钮。
 */
export default function ArtifactFileList({
  type = 'default',
  files,
  onPreview,
  onDownload,
  emptyText,
}: ArtifactFileListProps) {
  const { t } = useTranslation();

  if (files.length === 0) {
    return (
      <div className={drawerStyles.emptyState}>
        {emptyText ?? t("taskGraph.noFiles")}
      </div>
    );
  }

  return (
    <ul className={drawerStyles.fileList}>
      {files.map((file) => (
        <li key={file.path || file.name} className={drawerStyles.fileItem}>
          <div className={drawerStyles.fileInfo}>
            <span className={drawerStyles.fileName}>{file.name}</span>
            <div className={drawerStyles.fileMeta}>
              {file._nodeName ? (
                <span
                  style={{
                    fontSize: "11px",
                    color: "var(--colorTextTertiary, #9ca3af)",
                    background: "var(--color-fill-tertiary, #f3f4f6)",
                    padding: "1px 6px",
                    borderRadius: "4px",
                    flexShrink: 0,
                  }}
                >
                  {file._nodeName}
                </span>
              ) : null}
              {type !== "default" && file.path ? (
                <span className={drawerStyles.filePath} title={file.path}>
                  {file.path}
                </span>
              ) : null}
              <span className={drawerStyles.fileSize}>
                {file.size_bytes
                  ? `${(file.size_bytes / 1024).toFixed(1)} KB`
                  : ""}
              </span>
            </div>
          </div>
          <div className={drawerStyles.fileActions}>
            <button
              type="button"
              className={drawerStyles.backBtn}
              onClick={() => onPreview(file)}
            >
              {t("taskGraph.filePreview")}
            </button>
            <button
              type="button"
              className={drawerStyles.backBtn}
              onClick={() => void onDownload(file)}
            >
              {t("taskGraph.download")}
            </button>
          </div>
        </li>
      ))}
    </ul>
  );
}
