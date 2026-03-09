import { useAgentsData, FileListPanel, FileEditor } from "./components";
import styles from "./index.module.less";
import { UploadOutlined, DownloadOutlined } from "@ant-design/icons";
import { Button, Tooltip, message } from "@agentscope-ai/design";
import { workspaceApi } from "../../../api/modules/workspace";
import { useRef } from "react";
import { useTranslation } from "react-i18next";

export default function WorkspacePage() {
  const { t } = useTranslation();
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

  const handleDownload = async () => {
    try {
      const blob = await workspaceApi.downloadWorkspace();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `workspace-${new Date().toISOString().split("T")[0]}.zip`;
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

    const maxSize = 100 * 1024 * 1024;
    if (file.size > maxSize) {
      message.error(
        t("workspace.fileSizeExceeded", {
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
    <div className={styles.agentsPage}>
      <div className={styles.header}>
        <h1 className={styles.title}>{t("workspace.title")}</h1>
        <div className={styles.workspaceInfo}>
          <p className={styles.workspacePath}>
            {t("workspace.workspacePath")}{" "}
            {workspacePath ||
              (files.length === 0
                ? t("workspace.noFiles")
                : t("common.loading"))}
          </p>
          <div className={styles.actionButtons}>
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
      </div>

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

      <p className={styles.attribution}>{t("workspace.attribution")}</p>

      {/* Hidden file input - only accepts .zip files up to 100MB */}
      <input
        type="file"
        ref={fileInputRef}
        onChange={handleFileUpload}
        style={{ display: "none" }}
        accept=".zip"
        title="Select a ZIP file (max 100MB)"
      />
    </div>
  );
}
