import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Checkbox, Divider, Modal, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { checkpointsApi } from "@/api/modules/checkpoints";
import type {
  CheckpointNode,
  RestoreRequest,
  RestoreResult,
} from "@/api/types/checkpoints";
import { useAppMessage } from "@/hooks/useAppMessage";
import styles from "./index.module.less";

interface RestoreModalProps {
  open: boolean;
  node: CheckpointNode | null;
  onClose: () => void;
  onRestored: () => void;
}

export function RestoreModal({
  open,
  node,
  onClose,
  onRestored,
}: RestoreModalProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [includeMemory, setIncludeMemory] = useState(false);
  const [includeFiles, setIncludeFiles] = useState(false);
  const [preview, setPreview] = useState<RestoreResult | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<string[]>([]);
  const [previewing, setPreviewing] = useState(false);
  const [restoring, setRestoring] = useState(false);

  useEffect(() => {
    if (!open) return;
    setIncludeMemory(false);
    setIncludeFiles(false);
    setPreview(null);
    setSelectedFiles([]);
  }, [open, node?.commit]);

  const baseRequest = (): RestoreRequest => ({
    commit: node?.commit ?? "",
    session_id: node?.session_id ?? "",
    user_id: node?.user_id ?? "",
    channel: node?.channel ?? "console",
    include_memory: includeMemory,
    include_files: includeFiles,
  });

  const previewRestore = async () => {
    if (!node) return;
    setPreviewing(true);
    try {
      const result = await checkpointsApi.previewRestore(baseRequest());
      setPreview(result);
      setSelectedFiles([]);
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setPreviewing(false);
    }
  };

  const applyRestore = async () => {
    if (!node || !preview) return;
    setRestoring(true);
    try {
      await checkpointsApi.restore({
        ...baseRequest(),
        // Pin confirmation to the exact commit resolved by the preview.
        commit: preview.commit,
        files: includeFiles ? selectedFiles : undefined,
      });
      message.success(t("checkpoints.restore.success"));
      onClose();
      onRestored();
    } catch (error) {
      message.error((error as Error).message);
    } finally {
      setRestoring(false);
    }
  };

  const fileStatus = useMemo(() => {
    const deleted = new Set(preview?.deleted_paths ?? []);
    return (preview?.file_paths ?? []).map((path) => ({
      path,
      deleted: deleted.has(path),
    }));
  }, [preview]);

  const scopeChanged = () => {
    setPreview(null);
    setSelectedFiles([]);
  };

  return (
    <Modal
      open={open}
      title={t("checkpoints.restore.title")}
      onCancel={onClose}
      width={620}
      destroyOnHidden
      footer={
        preview
          ? [
              <Button
                key="back"
                onClick={() => setPreview(null)}
                disabled={restoring}
              >
                {t("common.back")}
              </Button>,
              <Button
                key="restore"
                type="primary"
                danger
                loading={restoring}
                disabled={includeFiles && selectedFiles.length === 0}
                onClick={applyRestore}
              >
                {t("checkpoints.restore.confirm")}
              </Button>,
            ]
          : [
              <Button key="cancel" onClick={onClose}>
                {t("common.cancel")}
              </Button>,
              <Button
                key="preview"
                type="primary"
                loading={previewing}
                onClick={previewRestore}
              >
                {t("checkpoints.restore.preview")}
              </Button>,
            ]
      }
    >
      <div className={styles.restoreBody}>
        <div className={styles.restoreTarget}>
          <span>{node?.query || node?.name || node?.subject}</span>
          <code>{node?.commit}</code>
        </div>
        {!preview ? (
          <div className={styles.scopeOptions}>
            <Checkbox checked disabled>
              {t("checkpoints.restore.conversation")}
            </Checkbox>
            <Checkbox
              checked={includeMemory}
              onChange={(event) => {
                setIncludeMemory(event.target.checked);
                scopeChanged();
              }}
            >
              {t("checkpoints.restore.memory")}
            </Checkbox>
            <Checkbox
              checked={includeFiles}
              onChange={(event) => {
                setIncludeFiles(event.target.checked);
                scopeChanged();
              }}
            >
              {t("checkpoints.restore.files")}
            </Checkbox>
          </div>
        ) : (
          <>
            <Alert
              type="warning"
              showIcon
              message={t("checkpoints.restore.refreshWarning")}
            />
            <div className={styles.previewSummary}>
              <span>{t("checkpoints.restore.conversation")}</span>
              {includeMemory && <span>{t("checkpoints.restore.memory")}</span>}
              {includeFiles && (
                <span>
                  {t("checkpoints.restore.selectedCount", {
                    count: selectedFiles.length,
                  })}
                </span>
              )}
            </div>
            {includeFiles && (
              <>
                <Divider />
                <Checkbox
                  indeterminate={
                    selectedFiles.length > 0 &&
                    selectedFiles.length < fileStatus.length
                  }
                  checked={
                    fileStatus.length > 0 &&
                    selectedFiles.length === fileStatus.length
                  }
                  onChange={(event) =>
                    setSelectedFiles(
                      event.target.checked
                        ? fileStatus.map((item) => item.path)
                        : [],
                    )
                  }
                >
                  {t("checkpoints.restore.selectAll")}
                </Checkbox>
                <div className={styles.fileSelection}>
                  {previewing ? (
                    <Spin size="small" />
                  ) : fileStatus.length ? (
                    fileStatus.map((item) => (
                      <Checkbox
                        key={item.path}
                        checked={selectedFiles.includes(item.path)}
                        onChange={(event) =>
                          setSelectedFiles((current) =>
                            event.target.checked
                              ? [...current, item.path]
                              : current.filter((path) => path !== item.path),
                          )
                        }
                      >
                        <code>{item.path}</code>
                        <span
                          className={
                            item.deleted
                              ? styles.deleteStatus
                              : styles.restoreStatus
                          }
                        >
                          {item.deleted
                            ? t("checkpoints.restore.delete")
                            : t("checkpoints.restore.restore")}
                        </span>
                      </Checkbox>
                    ))
                  ) : (
                    <span className={styles.muted}>
                      {t("checkpoints.restore.noFileChanges")}
                    </span>
                  )}
                </div>
              </>
            )}
          </>
        )}
      </div>
    </Modal>
  );
}
