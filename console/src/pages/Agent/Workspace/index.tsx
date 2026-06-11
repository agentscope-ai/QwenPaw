import { useAgentsData, FileListPanel, FileEditor } from "./components";
import styles from "./index.module.less";
import { Upload, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { workspaceApi } from "../../../api/modules/workspace";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { useUploadLimitStore } from "../../../stores/uploadLimitStore";
import { DownloadCancelledError } from "../../../utils/downloadFileFromUrl";

export default function WorkspacePage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const {
    files,
    selectedFile,
    dailyMemories,
    expandedMemory,
    fileContent,
    loading,
    workspacePath,
    hasChanges,
    enabledFiles,
    setFileContent,
    fetchFiles,
    handleFileClick,
    handleDailyMemoryClick,
    handleSave,
    handleReset,
    handleToggleFileEnabled,
    handleReorderFiles,
  } = useAgentsData();

  const fileInputRef = useRef<HTMLInputElement>(null);
  const [downloading, setDownloading] = useState(false);

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);
    message.loading({
      content: t("workspace.downloadPreparing"),
      key: "workspace-download",
      duration: 0,
    });
    try {
      await workspaceApi.downloadWorkspace();
      message.success({
        content: t("workspace.downloadSuccess"),
        key: "workspace-download",
      });
    } catch (error) {
      if (error instanceof DownloadCancelledError) {
        message.destroy("workspace-download");
        return;
      }
      console.error("Download failed:", error);
      message.error({
        content:
          t("workspace.downloadFailed") + ": " + (error as Error).message,
        key: "workspace-download",
      });
    } finally {
      setDownloading(false);
    }
  };

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.error(t("workspace.zipOnly"));
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }

    const uploadLimit = useUploadLimitStore.getState().uploadMaxSizeMb;
    if (uploadLimit !== null && file.size > uploadLimit * 1024 * 1024) {
      message.error(
        t("workspace.fileSizeExceeded", {
          limit: uploadLimit,
          size: (file.size / (1024 * 1024)).toFixed(2),
        }),
      );
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }

    try {
      const result = await workspaceApi.uploadFile(file);
      if (result.success) {
        message.success(t("workspace.uploadSuccess"));
      } else {
        message.error(t("workspace.uploadFailed") + ": " + result.message);
      }
    } catch (error) {
      console.error("Upload failed:", error);
      message.error(
        t("workspace.uploadFailed") + ": " + (error as Error).message,
      );
    } finally {
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  const handleUploadClick = () => {
    fileInputRef.current?.click();
  };

  return (
    <div className={styles.workspacePage}>
      <PageHeader
        items={[{ title: t("nav.agent") }, { title: t("workspace.title") }]}
        afterBreadcrumb={
          <p className={styles.workspacePath}>
            {t("workspace.workspacePath")}{" "}
            {workspacePath === null
              ? t("common.loading")
              : workspacePath || t("workspace.noFiles")}
          </p>
        }
        extra={
          <div className={styles.workspaceInfo}>
            <div className={styles.actionButtons}>
              <input
                type="file"
                ref={fileInputRef}
                onChange={handleFileUpload}
                style={{ display: "none" }}
                accept=".zip"
                title=""
              />
              <Button
                size="sm"
                variant="outline"
                title={`${t("workspace.coreFilesDesc")} (${
                  useUploadLimitStore.getState().uploadMaxSizeMb !== null
                    ? t("workspace.uploadTooltipWithLimit", {
                        limit: useUploadLimitStore.getState().uploadMaxSizeMb,
                      })
                    : t("workspace.uploadTooltip")
                })`}
                onClick={handleUploadClick}
              >
                <Upload size={14} className="mr-1" />
                {t("common.upload")}
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={handleDownload}
                disabled={downloading}
              >
                {downloading ? (
                  <span className="animate-pulse mr-1">...</span>
                ) : (
                  <Download size={14} className="mr-1" />
                )}
                {t("common.download")}
              </Button>
            </div>
          </div>
        }
      />

      <div className={styles.content}>
        <FileListPanel
          files={files}
          selectedFile={selectedFile}
          dailyMemories={dailyMemories}
          expandedMemory={expandedMemory}
          workspacePath={workspacePath}
          enabledFiles={enabledFiles}
          onRefresh={fetchFiles}
          onFileClick={handleFileClick}
          onDailyMemoryClick={handleDailyMemoryClick}
          onToggleEnabled={handleToggleFileEnabled}
          onReorder={handleReorderFiles}
        />

        <FileEditor
          selectedFile={selectedFile}
          fileContent={fileContent}
          loading={loading}
          hasChanges={hasChanges}
          onContentChange={setFileContent}
          onSave={handleSave}
          onReset={handleReset}
        />
      </div>
    </div>
  );
}
