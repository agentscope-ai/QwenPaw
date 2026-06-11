import React, { useState, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Copy, Undo2, Save } from "lucide-react";
import type { MarkdownFile } from "../../../../api/types";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { stripFrontmatter } from "../../../../utils/markdown";
import { mermaidComponents } from "../../../../components/MermaidCodeBlock";
import styles from "../index.module.less";

interface FileEditorProps {
  selectedFile: MarkdownFile | null;
  fileContent: string;
  loading: boolean;
  hasChanges: boolean;
  onContentChange: (content: string) => void;
  onSave: () => void;
  onReset: () => void;
}

export const FileEditor: React.FC<FileEditorProps> = ({
  selectedFile,
  fileContent,
  loading,
  hasChanges,
  onContentChange,
  onSave,
  onReset,
}) => {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [showMarkdown, setShowMarkdown] = useState(true);

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

  return (
    <div className={styles.fileEditor}>
      <Card className={styles.editorCard}>
        <CardContent className="p-0">
          {selectedFile ? (
            <>
              <div className={styles.editorHeader}>
                <div>
                  <div className={styles.fileName}>{selectedFile.filename}</div>
                  <div className={styles.filePath}>{selectedFile.path}</div>
                </div>
                <div className={styles.buttonGroup}>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={onReset}
                    disabled={!hasChanges}
                  >
                    <Undo2 size={14} className="mr-1" />
                    {t("common.reset")}
                  </Button>
                  <Button
                    size="sm"
                    onClick={onSave}
                    disabled={!hasChanges || loading}
                  >
                    {loading ? (
                      <span className="animate-pulse mr-1">...</span>
                    ) : (
                      <Save size={14} className="mr-1" />
                    )}
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
                          onCheckedChange={setShowMarkdown}
                        />
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={copyToClipboard}
                        className={styles.copyButton}
                      >
                        <Copy size={14} />
                      </Button>
                    </div>
                  )}
                </div>
                {showMarkdown && isMarkdownFile ? (
                  <div className={styles.markdownViewer}>
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={mermaidComponents}
                    >
                      {markdownContent}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <Textarea
                    value={fileContent}
                    onChange={(e) => onContentChange(e.target.value)}
                    className={styles.textarea}
                    placeholder={t("workspace.fileContent")}
                  />
                )}
              </div>
            </>
          ) : (
            <div className={styles.emptyState}>{t("workspace.selectFile")}</div>
          )}
          <p className={styles.attribution}>{t("workspace.attribution")}</p>
        </CardContent>
      </Card>
    </div>
  );
};
