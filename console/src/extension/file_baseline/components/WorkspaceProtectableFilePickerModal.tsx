import { useCallback, useEffect, useState } from "react";
import { Button, Modal } from "@agentscope-ai/design";
import { Modal as AntModal, message } from "antd";
import { ChevronRight, FileText, Folder } from "lucide-react";
import { useTranslation } from "react-i18next";
import {
  fileBaselineApi,
  type FileBaselineWorkspaceBrowseEntry,
  type FileBaselineWorkspaceBrowseResponse,
} from "../api/client";
import styles from "./WorkspaceProtectableFilePickerModal.module.less";

export interface WorkspaceProtectableFilePickerModalProps {
  open: boolean;
  protectedPaths: string[];
  onClose: () => void;
  onAdd: (relPath: string) => Promise<void>;
}

function formatCurrentPath(currentPath: string, defaultPath: string): string {
  if (!currentPath) {
    return defaultPath || "/";
  }
  return currentPath;
}

export function WorkspaceProtectableFilePickerModal({
  open,
  protectedPaths,
  onClose,
  onAdd,
}: WorkspaceProtectableFilePickerModalProps) {
  const { t } = useTranslation();
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [browse, setBrowse] = useState<FileBaselineWorkspaceBrowseResponse | null>(
    null,
  );
  const [selectedFile, setSelectedFile] =
    useState<FileBaselineWorkspaceBrowseEntry | null>(null);

  const loadBrowse = useCallback(async (path?: string) => {
    setLoading(true);
    try {
      const next = await fileBaselineApi.browseWorkspaceProtectableFiles(path);
      setBrowse(next);
      setSelectedFile(null);
    } catch {
      message.error(t("security.integrityProtection.workspacePickerLoadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    if (!open) {
      setBrowse(null);
      setSelectedFile(null);
      return;
    }
    void loadBrowse("skills");
  }, [loadBrowse, open]);

  const navigateTo = (path: string) => {
    void loadBrowse(path);
  };

  const handleEntryClick = (entry: FileBaselineWorkspaceBrowseEntry) => {
    if (entry.type === "dir") {
      navigateTo(entry.rel_path);
      return;
    }
    setSelectedFile(entry);
  };

  const confirmAdd = async (relPath: string) => {
    const normalized = relPath.replace(/\\/g, "/").replace(/^\/+/, "").trim();
    if (!normalized) {
      return;
    }
    if (protectedPaths.includes(normalized)) {
      message.warning(t("security.integrityProtection.protectedPathDuplicate"));
      return;
    }
    setSubmitting(true);
    try {
      await onAdd(normalized);
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  const handleAdd = () => {
    if (!selectedFile || selectedFile.type !== "file") {
      return;
    }
    const relPath = selectedFile.rel_path;
    const baseName = selectedFile.name.toLowerCase();
    if (baseName === "agent.json") {
      AntModal.confirm({
        title: t("security.integrityProtection.workspacePickerAgentJsonTitle"),
        content: t("security.integrityProtection.workspacePickerAgentJsonBody"),
        okText: t("common.confirm"),
        cancelText: t("common.cancel"),
        onOk: () => confirmAdd(relPath),
      });
      return;
    }
    void confirmAdd(relPath);
  };

  const currentLabel = browse
    ? formatCurrentPath(browse.current_path, browse.default_path)
    : "skills";

  return (
    <Modal
      open={open}
      title={t("security.integrityProtection.workspacePickerTitle")}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          {t("common.cancel")}
        </Button>,
        <Button
          key="add"
          type="primary"
          data-testid="workspace-picker-add"
          loading={submitting}
          disabled={!selectedFile}
          onClick={handleAdd}
        >
          {t("security.integrityProtection.workspacePickerAdd")}
        </Button>,
      ]}
      width={560}
      destroyOnHidden
    >
      {browse ? (
        <div className={styles.meta}>
          <span>
            {t("security.integrityProtection.workspacePickerAgent", {
              agentId: browse.agent_id,
            })}
          </span>
          <span className={styles.metaPath}>
            {t("security.integrityProtection.workspacePickerLocation", {
              path: currentLabel,
            })}
          </span>
        </div>
      ) : null}

      <div className={styles.toolbar}>
        <Button
          size="small"
          disabled={loading || !browse || !browse.current_path}
          onClick={() => navigateTo(browse?.parent_path ?? "")}
        >
          {t("security.integrityProtection.workspacePickerUp")}
        </Button>
        {browse?.default_path ? (
          <Button
            size="small"
            disabled={loading}
            onClick={() => navigateTo(browse.default_path)}
          >
            {t("security.integrityProtection.workspacePickerSkills")}
          </Button>
        ) : null}
        <Button
          size="small"
          disabled={loading}
          onClick={() => navigateTo("")}
        >
          {t("security.integrityProtection.workspacePickerRoot")}
        </Button>
      </div>

      <div className={styles.list} aria-busy={loading}>
        {loading && !browse ? (
          <p className={styles.empty}>
            {t("security.integrityProtection.workspacePickerLoading")}
          </p>
        ) : null}
        {!loading && browse && browse.entries.length === 0 ? (
          <p className={styles.empty}>
            {t("security.integrityProtection.workspacePickerEmpty")}
          </p>
        ) : null}
        {browse?.entries.map((entry) => {
          const selected = selectedFile?.rel_path === entry.rel_path;
          return (
            <button
              key={entry.rel_path}
              type="button"
              className={`${styles.entry} ${selected ? styles.entrySelected : ""}`}
              onClick={() => handleEntryClick(entry)}
              onDoubleClick={() => {
                if (entry.type === "dir") {
                  navigateTo(entry.rel_path);
                }
              }}
            >
              {entry.type === "dir" ? (
                <Folder size={16} className={styles.entryIcon} />
              ) : (
                <FileText size={16} className={styles.entryIcon} />
              )}
              <span className={styles.entryName}>{entry.name}</span>
              {entry.type === "dir" ? (
                <ChevronRight size={14} className={styles.entryChevron} />
              ) : null}
            </button>
          );
        })}
      </div>

      <div className={styles.selectionPreview}>
        {selectedFile
          ? t("security.integrityProtection.workspacePickerSelected", {
              path: selectedFile.rel_path,
            })
          : t("security.integrityProtection.workspacePickerSelectHint")}
      </div>
    </Modal>
  );
}
