import {
  Calendar as CalendarFilled,
  FileCode as CodeFilled,
  Sheet as FileExcelFilled,
  FileImage as FileImageFilled,
  FileText as FilePdfFilled,
  Presentation as FilePptFilled,
  FileText as FileTextFilled,
  FileText as FileWordFilled,
  FileArchive as FileZipFilled,
} from "lucide-react";

const normalizeSkillIconKey = (value: string) =>
  value
    .trim()
    .toLowerCase()
    .split(/\s+/)[0]
    ?.replace(/[^a-z0-9_-]/g, "") || "";

export const getFileIcon = (filePath: string) => {
  const skillKey = normalizeSkillIconKey(filePath);
  const textSkillIcons = new Set([
    "news",
    "file_reader",
    "browser",
    "guidance",
    "dingtalk_channel",
  ]);

  if (textSkillIcons.has(skillKey)) {
    return (
      <FileTextFilled size="1em" style={{ color: "var(--app-accent-text)" }} />
    );
  }

  switch (skillKey) {
    case "docx":
      return (
        <FileWordFilled
          size="1em"
          style={{ color: "var(--app-accent-text)" }}
        />
      );
    case "xlsx":
      return (
        <FileExcelFilled
          size="1em"
          style={{ color: "var(--app-accent-text)" }}
        />
      );
    case "pptx":
      return (
        <FilePptFilled size="1em" style={{ color: "var(--app-accent-text)" }} />
      );
    case "pdf":
      return (
        <FilePdfFilled size="1em" style={{ color: "var(--app-accent-text)" }} />
      );
    case "cron":
      return (
        <CalendarFilled
          size="1em"
          style={{ color: "var(--app-accent-text)" }}
        />
      );
    default:
      break;
  }

  const extension = filePath.split(".").pop()?.toLowerCase() || "";

  switch (extension) {
    case "txt":
    case "md":
    case "markdown":
      return (
        <FileTextFilled
          size="1em"
          style={{ color: "var(--app-accent-text)" }}
        />
      );
    case "zip":
    case "rar":
    case "7z":
    case "tar":
    case "gz":
      return (
        <FileZipFilled size="1em" style={{ color: "var(--app-accent-text)" }} />
      );
    case "pdf":
      return (
        <FilePdfFilled size="1em" style={{ color: "var(--app-accent-text)" }} />
      );
    case "doc":
    case "docx":
      return (
        <FileWordFilled
          size="1em"
          style={{ color: "var(--app-accent-text)" }}
        />
      );
    case "xls":
    case "xlsx":
      return (
        <FileExcelFilled
          size="1em"
          style={{ color: "var(--app-accent-text)" }}
        />
      );
    case "ppt":
    case "pptx":
      return (
        <FilePptFilled size="1em" style={{ color: "var(--app-accent-text)" }} />
      );
    case "jpg":
    case "jpeg":
    case "png":
    case "gif":
    case "svg":
    case "webp":
      return (
        <FileImageFilled
          size="1em"
          style={{ color: "var(--app-accent-text)" }}
        />
      );
    case "py":
    case "js":
    case "ts":
    case "jsx":
    case "tsx":
    case "java":
    case "cpp":
    case "c":
    case "go":
    case "rs":
    case "rb":
    case "php":
      return (
        <CodeFilled size="1em" style={{ color: "var(--app-accent-text)" }} />
      );
    default:
      return (
        <FileTextFilled
          size="1em"
          style={{ color: "var(--app-accent-text)" }}
        />
      );
  }
};

interface SkillVisualProps {
  name: string;
  emoji?: string;
  /** CSS class applied to the emoji wrapper span */
  emojiClassName?: string;
}

/** Product skill tiles use Lucide glyphs; skill metadata remains unchanged. */
export function SkillVisual({ name, emojiClassName }: SkillVisualProps) {
  return (
    <span className={emojiClassName} aria-hidden="true">
      {getFileIcon(name)}
    </span>
  );
}
