import { useAgentsData, FileListPanel, FileEditor } from "./components";
import styles from "./index.module.less";
import { UploadOutlined, DownloadOutlined } from "@ant-design/icons";
import { Button, Tooltip } from "@agentscope-ai/design";
import { workspaceApi } from "../../../api/modules/workspace";
import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { PageHeader } from "@/components/PageHeader";
import { useAppMessage } from "../../../hooks/useAppMessage";

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
    listLoading,
    workspacePath,
    hasChanges,
    enabledFiles,
    viewMode,
    setViewMode,
    setFileContent,
    fetchFiles,
    handleFileClick,
    handleDailyMemoryClick,
    handleSave,
    handleReset,
    handleToggleFileEnabled,
    handleReorderFiles,
    handleDownloadSelected,
  } = useAgentsData();

  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDownload = async () => {
    try {
      const { blob, filename } = await workspaceApi.downloadWorkspace();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
      message.success(t("workspace.downloadSuccess"));
    } catch (error) {
      console.error("Download failed:", error);
      message.error(
        t("workspace.downloadFailed") + ": " + (error as Error).message,
      );
    }
  };

  const handleFileUpload = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;

    // Check if file is zip format
    if (!file.name.toLowerCase().endsWith(".zip")) {
      message.error(t("workspace.zipOnly"));
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
      return;
    }

    const maxSizeMb = 100;
    const maxSize = maxSizeMb * 1024 * 1024;
    if (file.size > maxSize) {
      message.error(
        t("workspace.fileSizeExceeded", {
          limit: maxSizeMb,
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
      // Clear input value to allow re-uploading the same file
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
                title="Select a ZIP file (max 100MB)"
              />
              <Tooltip
                title={t("workspace.uploadTooltip")}
                placement="top"
                mouseEnterDelay={0.5}
              >
                <Button
                  size="small"
                  onClick={handleUploadClick}
                  icon={<UploadOutlined />}
                >
                  {t("common.upload")}
                </Button>
              </Tooltip>
              <Button
                size="small"
                onClick={handleDownload}
                icon={<DownloadOutlined />}
              >
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
          viewMode={viewMode}
          onViewModeChange={setViewMode}
          onRefresh={fetchFiles}
          listLoading={listLoading}
          onFileClick={handleFileClick}
          onDailyMemoryClick={handleDailyMemoryClick}
          onToggleEnabled={handleToggleFileEnabled}
          onReorder={handleReorderFiles}
          onDownloadSelected={handleDownloadSelected}
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
