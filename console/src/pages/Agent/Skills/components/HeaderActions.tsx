import { Button, Tooltip } from "@agentscope-ai/design";
import {
  X as CloseOutlined,
  Trash2 as DeleteOutlined,
  RefreshCw as ReloadOutlined,
  ArrowLeftRight as SwapOutlined,
  Eye as EyeOutlined,
  EyeOff as EyeInvisibleOutlined,
} from "lucide-react";
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
              icon={<CloseOutlined size="1em" />}
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
                icon={<SwapOutlined size="1em" />}
              >
                {t("skills.uploadToPool")}
              </Button>
            </Tooltip>
            <Button
              type="default"
              icon={<EyeOutlined size="1em" />}
              onClick={onBatchEnable}
            >
              {t("skills.batchEnable")}
            </Button>
            <Button
              danger
              icon={<EyeInvisibleOutlined size="1em" />}
              onClick={onBatchDisable}
            >
              {t("skills.batchDisable")}
            </Button>
            <Button
              danger
              icon={<DeleteOutlined size="1em" />}
              onClick={onBatchDelete}
            >
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
                icon={<ReloadOutlined size="1em" data-spinning={loading} />}
                onClick={onHardRefresh}
                disabled={loading}
              />
            </Tooltip>
            <Tooltip title={t("skills.uploadToPoolHint")}>
              <Button
                type="default"
                className={styles.primaryTransferButton}
                onClick={onOpenUploadPool}
                icon={<SwapOutlined size="1em" />}
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
