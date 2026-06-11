import { Button } from "@/components/ui/button";
import {
  X,
  Trash2,
  Download,
  Import,
  Plus,
  RefreshCw,
  ArrowLeftRight,
  Upload,
  Eye,
  EyeOff,
} from "lucide-react";
import { useTranslation } from "react-i18next";
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
            <Button variant="outline" size="sm" onClick={onSelectAll}>
              {t("skills.selectAll")}
            </Button>
            <Button variant="outline" size="sm" onClick={onClearSelection}>
              <X size={14} className="mr-1" />
              {t("skills.clearSelection")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={styles.primaryTransferButton}
              title={t("skills.uploadToPoolHint")}
              onClick={() => {
                const names = Array.from(selectedSkills);
                if (names.length === 0) return;
                onClearSelection();
                void onUploadToPool(names);
              }}
            >
              <ArrowLeftRight size={14} className="mr-1" />
              {t("skills.uploadToPool")}
            </Button>
            <Button variant="outline" size="sm" onClick={onBatchEnable}>
              <Eye size={14} className="mr-1" />
              {t("skills.batchEnable")}
            </Button>
            <Button variant="destructive" size="sm" onClick={onBatchDisable}>
              <EyeOff size={14} className="mr-1" />
              {t("skills.batchDisable")}
            </Button>
            <Button variant="destructive" size="sm" onClick={onBatchDelete}>
              <Trash2 size={14} className="mr-1" />
              {t("common.delete")} ({selectedSkills.size})
            </Button>
          </>
          <Button size="sm" onClick={onToggleBatchMode}>
            {t("skills.exitBatch")}
          </Button>
        </div>
      ) : (
        <>
          <div className={styles.headerActionsLeft}>
            <Button
              variant="outline"
              size="sm"
              title={t("skills.refreshHint")}
              onClick={onHardRefresh}
              disabled={loading}
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={styles.primaryTransferButton}
              title={t("skills.downloadFromPoolHint")}
              onClick={onOpenDownloadPool}
            >
              <Download size={14} className="mr-1" />
              {t("skills.downloadFromPool")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={styles.primaryTransferButton}
              title={t("skills.uploadToPoolHint")}
              onClick={onOpenUploadPool}
            >
              <ArrowLeftRight size={14} className="mr-1" />
              {t("skills.uploadToPool")}
            </Button>
          </div>
          <div className={styles.headerActionsRight}>
            <Button
              variant="outline"
              size="sm"
              className={styles.creationActionButton}
              title={t("skills.uploadZipHint")}
              onClick={onUploadClick}
              disabled={uploading}
            >
              {uploading ? (
                <RefreshCw size={14} className="animate-spin mr-1" />
              ) : (
                <Upload size={14} className="mr-1" />
              )}
              {t("skills.uploadZip")}
            </Button>
            <Button
              variant="outline"
              size="sm"
              className={styles.creationActionButton}
              title={t("skills.importHubHint")}
              onClick={onImportHub}
            >
              <Import size={14} className="mr-1" />
              {t("skills.importHub")}
            </Button>
            <Button size="sm" onClick={onToggleBatchMode}>
              {t("skills.batchOperation")}
            </Button>
            <Button
              size="sm"
              className={styles.primaryActionButton}
              title={t("skills.createSkillHint")}
              onClick={onCreate}
            >
              <Plus size={14} className="mr-1" />
              {t("skills.createSkill")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
