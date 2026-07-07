import { Button, Tooltip } from "@agentscope-ai/design";
import {
  CloseOutlined,
  DeleteOutlined,
  ReloadOutlined,
  SwapOutlined,
  EyeOutlined,
  EyeInvisibleOutlined,
} from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import { AddSkillDropdown } from "./AddSkillDropdown";
import styles from "../index.module.less";

interface HeaderActionsProps {
  batchModeEnabled: boolean;
  selectedSkills: Set<string>;
  loading: boolean;
  uploading: boolean;
  fileInputRef: React.RefObject<HTMLInputElement>;
  onSelectAll: () => void;
  onClearSelection: () => void;
  onUploadToPool: (names: string[]) => void;
  onBatchEnable: () => void;
  onBatchDisable: () => void;
  onBatchDelete: () => void;
  onToggleBatchMode: () => void;
  onHardRefresh: () => void;
  onOpenDownloadPool: () => void;
  onOpenUploadPool: () => void;
  onUploadClick: () => void;
  onImportHub: () => void;
  onCreate: () => void;
  onBrowseMarket: () => void;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export function HeaderActions({
  batchModeEnabled,
  selectedSkills,
  loading,
  uploading,
  fileInputRef,
  onSelectAll,
  onClearSelection,
  onUploadToPool,
  onBatchEnable,
  onBatchDisable,
  onBatchDelete,
  onToggleBatchMode,
  onHardRefresh,
  onOpenDownloadPool,
  onOpenUploadPool,
  onUploadClick,
  onImportHub,
  onCreate,
  onBrowseMarket,
  onFileChange,
}: HeaderActionsProps) {
  const { t } = useTranslation();

  return (
    <div className={styles.headerRight}>
      <input
        type="file"
        accept=".zip"
        ref={fileInputRef}
        onChange={onFileChange}
        style={{ display: "none" }}
      />
      {batchModeEnabled ? (
        <div className={styles.batchActions}>
          <>
            <span className={styles.batchCount}>
              {t("skills.selectedCount", { count: selectedSkills.size })}
            </span>
            <Button type="default" onClick={onSelectAll}>
              {t("skills.selectAll")}
            </Button>
            <Button
              type="default"
              onClick={onClearSelection}
              icon={<CloseOutlined />}
            >
              {t("skills.clearSelection")}
            </Button>
            <Tooltip title={t("skills.uploadToPoolHint")}>
              <Button
                type="default"
                className={styles.primaryTransferButton}
                onClick={() => {
                  const names = Array.from(selectedSkills);
                  if (names.length === 0) return;
                  onClearSelection();
                  void onUploadToPool(names);
                }}
                icon={<SwapOutlined />}
              >
                {t("skills.uploadToPool")}
              </Button>
            </Tooltip>
            <Button
              type="default"
              icon={<EyeOutlined />}
              onClick={onBatchEnable}
            >
              {t("skills.batchEnable")}
            </Button>
            <Button
              danger
              icon={<EyeInvisibleOutlined />}
              onClick={onBatchDisable}
            >
              {t("skills.batchDisable")}
            </Button>
            <Button danger icon={<DeleteOutlined />} onClick={onBatchDelete}>
              {t("common.delete")} ({selectedSkills.size})
            </Button>
          </>
          <Button type="primary" onClick={onToggleBatchMode}>
            {t("skills.exitBatch")}
          </Button>
        </div>
      ) : (
        <>
          <div className={styles.headerActionsLeft}>
            <Tooltip title={t("skills.refreshHint")}>
              <Button
                type="default"
                icon={<ReloadOutlined spin={loading} />}
                onClick={onHardRefresh}
                disabled={loading}
              />
            </Tooltip>
            <Tooltip title={t("skills.uploadToPoolHint")}>
              <Button
                type="default"
                className={styles.primaryTransferButton}
                onClick={onOpenUploadPool}
                icon={<SwapOutlined />}
              >
                {t("skills.uploadToPool")}
              </Button>
            </Tooltip>
          </div>
          <div className={styles.headerActionsRight}>
            <Button type="primary" onClick={onToggleBatchMode}>
              {t("skills.batchOperation")}
            </Button>
            <AddSkillDropdown
              onCreate={onCreate}
              onFromPool={onOpenDownloadPool}
              onUploadZip={onUploadClick}
              onFromUrl={onImportHub}
              onBrowseMarket={onBrowseMarket}
              uploading={uploading}
            />
          </div>
        </>
      )}
    </div>
  );
}
