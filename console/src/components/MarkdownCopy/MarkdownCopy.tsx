import { useState, useEffect, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Copy } from "lucide-react";
import { useTranslation } from "react-i18next";
import type { CSSProperties } from "react";
import { useAppMessage } from "../../hooks/useAppMessage";
import { stripFrontmatter } from "../../utils/markdown";
import { mermaidComponents } from "../MermaidCodeBlock";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";

interface MarkdownCopyProps {
  content: string;
  showMarkdown?: boolean;
  onShowMarkdownChange?: (show: boolean) => void;
  copyButtonProps?: {
    type?:
      | "text"
      | "link"
      | "default"
      | "primary"
      | "dashed"
      | "primaryLess"
      | "textCompact"
      | undefined;
    size?: "small" | "middle" | "large" | undefined;
    style?: CSSProperties;
  };
  markdownViewerProps?: {
    style?: CSSProperties;
    className?: string;
  };
  textareaProps?: {
    rows?: number;
    placeholder?: string;
    disabled?: boolean;
    style?: CSSProperties;
    className?: string;
  };
  showControls?: boolean;
  editable?: boolean;
  onContentChange?: (content: string) => void;
}

export function MarkdownCopy({
  content,
  showMarkdown = true,
  onShowMarkdownChange,
  copyButtonProps = {},
  markdownViewerProps = {},
  textareaProps = {},
  showControls = true,
  editable = false,
  onContentChange,
}: MarkdownCopyProps) {
  const { t } = useTranslation();
  const { message } = useAppMessage();
  const [isCopying, setIsCopying] = useState(false);
  const [editContent, setEditContent] = useState(content);
  const [localShowMarkdown, setLocalShowMarkdown] = useState(showMarkdown);
  const markdownContent = useMemo(
    () => stripFrontmatter(content || ""),
    [content],
  );

  useEffect(() => {
    setEditContent(content);
  }, [content]);

  useEffect(() => {
    if (editable && !textareaProps.disabled) {
      setLocalShowMarkdown(false);
    } else {
      setLocalShowMarkdown(showMarkdown);
    }
  }, [editable, textareaProps.disabled, showMarkdown]);

  const copyToClipboard = async () => {
    const contentToCopy =
      localShowMarkdown && !(editable && !textareaProps.disabled)
        ? content
        : editable
        ? editContent
        : content;

    if (!contentToCopy) return;

    setIsCopying(true);
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(contentToCopy);
        message.success(t("common.copied"));
      } else {
        const textArea = document.createElement("textarea");
        textArea.value = contentToCopy;
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
    } finally {
      setIsCopying(false);
    }
  };

  const handleContentChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newContent = e.target.value;
    setEditContent(newContent);
    if (onContentChange) {
      onContentChange(newContent);
    }
  };

  const handleShowMarkdownChange = (checked: boolean) => {
    setLocalShowMarkdown(checked);
    if (onShowMarkdownChange) {
      onShowMarkdownChange(checked);
    }
  };

  const switchId = "markdown-preview-toggle";

  return (
    <div className={cn("flex flex-col gap-2", copyButtonProps.style ? "" : "")}>
      {showControls && (
        <div className="flex items-center justify-between gap-2">
          <span className="text-sm font-medium">{t("common.content")}</span>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5">
              <Label
                htmlFor={switchId}
                className="text-sm cursor-pointer select-none"
              >
                {t("common.preview")}
              </Label>
              <Switch
                id={switchId}
                checked={localShowMarkdown}
                onCheckedChange={handleShowMarkdownChange}
              />
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 p-0"
              onClick={copyToClipboard}
              disabled={isCopying}
              aria-label={t("common.copied")}
            >
              <Copy size={14} />
            </Button>
          </div>
        </div>
      )}

      {localShowMarkdown ? (
        <div
          className={cn(
            "prose prose-sm dark-mode:prose-invert max-w-none p-4 overflow-auto rounded-md bg-white border",
            markdownViewerProps.className,
          )}
          style={markdownViewerProps.style}
        >
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={mermaidComponents as any}
          >
            {markdownContent}
          </ReactMarkdown>
        </div>
      ) : (
        <Textarea
          value={editable ? editContent : content}
          onChange={handleContentChange}
          rows={textareaProps.rows ?? 12}
          placeholder={
            textareaProps.placeholder ?? t("common.contentPlaceholder")
          }
          disabled={textareaProps.disabled}
          readOnly={!editable || textareaProps.disabled}
          className={cn("font-mono text-sm resize-y", textareaProps.className)}
          style={textareaProps.style}
        />
      )}
    </div>
  );
}
