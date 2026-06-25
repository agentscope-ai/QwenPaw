import React, { useState, useMemo } from "react";
import { Button, Card, Input, Switch } from "@agentscope-ai/design";
import {
  CopyOutlined,
  UndoOutlined,
  SaveOutlined,
  ArrowLeftOutlined,
} from "@ant-design/icons";
import type { MarkdownFile } from "../../../../api/types";
import { XMarkdown } from "@ant-design/x-markdown";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { stripFrontmatter } from "../../../../utils/markdown";
import { mermaidComponents } from "../../../../components/MermaidCodeBlock";
import styles from "../index.module.less";

interface FileEditorProps {
  selectedFile: MarkdownFile | null;
  fileContent: string;
  hasChanges: boolean;
  saving?: boolean;
  onContentChange: (content: string) => void;
  onSave: () => void | Promise<void>;
  onReset: () => void;
  onBack?: () => void;
  compact?: boolean;
}

export const FileEditor: React.FC<FileEditorProps> = ({
  selectedFile,
  fileContent,
  hasChanges,
  saving,
  onContentChange,
  onSave,
  onReset,
  onBack,
  compact,
}) => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [showMarkdown, setShowMarkdown] = useState(true);
  const [touchStart, setTouchStart] = useState<{ x: number; y: number } | null>(
    null,
  );

  const isMarkdownFile = selectedFile?.filename.endsWith(".md") || false;
  const markdownContent = useMemo(
    () => stripFrontmatter(fileContent || ""),
    [fileContent],
  );

  const copyToClipboard = async () => {
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(fileContent);
        message.success(t("common.copied"));
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = fileContent;
        textArea.style.position = "fixed";
        textArea.style.left = "-999999px";
        textArea.style.top = "-999999px";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        document.execCommand("copy");
        textArea.remove();
        message.success(t("common.copied"));
      }
    } catch (err) {
      console.error("Failed to copy text: ", err);
      message.error(t("common.copyFailed"));
    }
  };

  const handleTouchStart = (e: React.TouchEvent) => {
    if (!onBack) return;
    setTouchStart({ x: e.touches[0].clientX, y: e.touches[0].clientY });
  };

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (!touchStart || !onBack) return;
    const endX = e.changedTouches[0].clientX;
    const endY = e.changedTouches[0].clientY;
    const dx = endX - touchStart.x;
    const dy = endY - touchStart.y;
    if (dx > 80 && Math.abs(dx) > Math.abs(dy) * 1.5) {
      onBack();
    }
    setTouchStart(null);
  };

  return (
    <div
      className={styles.fileEditor}
      onTouchStart={handleTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      <Card className={styles.editorCard}>
        {selectedFile ? (
          <>
            {compact && onBack && (
              <div className={styles.mobileToolbar}>
                <Button
                  type="text"
                  size="small"
                  icon={<ArrowLeftOutlined />}
                  onClick={onBack}
                >
                  {t("common.back")}
                </Button>
                <span className={styles.mobileToolbarTitle}>
                  {selectedFile.filename}
                </span>
              </div>
            )}
            <div
              className={
                compact
                  ? `${styles.editorHeader} ${styles.editorHeaderCompact}`
                  : styles.editorHeader
              }
            >
              <div className={compact ? styles.fileMetaCompact : ""}>
                {!compact && (
                  <div className={styles.fileName}>{selectedFile.filename}</div>
                )}
                <div className={styles.filePath}>{selectedFile.path}</div>
              </div>
              <div className={styles.buttonGroup}>
                <span className={styles.saveStatus}>
                  {saving
                    ? t("workspace.saving")
                    : hasChanges
                    ? t("workspace.unsaved")
                    : t("workspace.saved")}
                </span>
                <Button
                  size="small"
                  onClick={onReset}
                  disabled={!hasChanges}
                  icon={<UndoOutlined />}
                >
                  {t("common.reset")}
                </Button>
                <Button
                  type="primary"
                  size="small"
                  onClick={onSave}
                  disabled={!hasChanges}
                  loading={saving}
                  icon={<SaveOutlined />}
                >
                  {t("common.save")}
                </Button>
              </div>
            </div>

            <div className={styles.editorContent}>
              <div className={styles.contentLabel}>
                <div>{t("common.content")}</div>
                {isMarkdownFile && (
                  <div className={styles.buttonGroup}>
                    <div className={styles.markdownToggle}>
                      <span className={styles.toggleLabel}>
                        {t("common.preview")}
                      </span>
                      <Switch
                        checked={showMarkdown}
                        onChange={setShowMarkdown}
                        size="small"
                      />
                    </div>
                    <Button
                      icon={<CopyOutlined />}
                      type="text"
                      onClick={copyToClipboard}
                      className={styles.copyButton}
                    />
                  </div>
                )}
              </div>
              {showMarkdown && isMarkdownFile ? (
                <XMarkdown
                  content={markdownContent}
                  className={styles.markdownViewer}
                  components={mermaidComponents}
                  dompurifyConfig={{
                    ADD_TAGS: ["pre", "code"],
                    ADD_ATTR: [
                      "data-block",
                      "data-state",
                      "data-lang",
                      "class",
                    ],
                  }}
                />
              ) : (
                <Input.TextArea
                  value={fileContent}
                  onChange={(e) => onContentChange(e.target.value)}
                  className={styles.textarea}
                  placeholder={t("workspace.fileContent")}
                  autoSize={
                    compact
                      ? { minRows: 15, maxRows: 40 }
                      : { minRows: 6, maxRows: 20 }
                  }
                />
              )}
            </div>
          </>
        ) : (
          <div className={styles.emptyState}>{t("workspace.selectFile")}</div>
        )}
        <p className={styles.attribution}>{t("workspace.attribution")}</p>
      </Card>
    </div>
  );
};
