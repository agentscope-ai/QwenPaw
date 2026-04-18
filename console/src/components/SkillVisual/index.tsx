import {
  CalendarFilled,
  CodeFilled,
  FileExcelFilled,
  FileImageFilled,
  FilePdfFilled,
  FilePptFilled,
  FileTextFilled,
  FileWordFilled,
  FileZipFilled,
} from "@ant-design/icons";

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
    "browser_visible",
    "guidance",
    "himalaya",
    "dingtalk_channel",
  ]);

  if (textSkillIcons.has(skillKey)) {
    return <FileTextFilled style={{ color: "#1890ff" }} />;
  }

  switch (skillKey) {
    case "docx":
      return <FileWordFilled style={{ color: "#2B8DFF" }} />;
    case "xlsx":
      return <FileExcelFilled style={{ color: "#44C161" }} />;
    case "pptx":
      return <FilePptFilled style={{ color: "#FF5B3B" }} />;
    case "pdf":
      return <FilePdfFilled style={{ color: "#F04B57" }} />;
    case "cron":
      return <CalendarFilled style={{ color: "#13c2c2" }} />;
    default:
      break;
  }

  const extension = filePath.split(".").pop()?.toLowerCase() || "";

  switch (extension) {
    case "txt":
    case "md":
    case "markdown":
      return <FileTextFilled style={{ color: "#1890ff" }} />;
    case "zip":
    case "rar":
    case "7z":
    case "tar":
    case "gz":
      return <FileZipFilled style={{ color: "#fa8c16" }} />;
    case "pdf":
      return <FilePdfFilled style={{ color: "#F04B57" }} />;
    case "doc":
    case "docx":
      return <FileWordFilled style={{ color: "#2B8DFF" }} />;
    case "xls":
    case "xlsx":
      return <FileExcelFilled style={{ color: "#44C161" }} />;
    case "ppt":
    case "pptx":
      return <FilePptFilled style={{ color: "#FF5B3B" }} />;
    case "jpg":
    case "jpeg":
    case "png":
    case "gif":
    case "svg":
    case "webp":
      return <FileImageFilled style={{ color: "#eb2f96" }} />;
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
      return <CodeFilled style={{ color: "#52c41a" }} />;
    default:
      return <FileTextFilled style={{ color: "#1890ff" }} />;
  }
};

interface SkillVisualProps {
  name: string;
  emoji?: string;
  /** CSS class applied to the emoji wrapper span */
  emojiClassName?: string;
}

/**
 * Renders either an emoji (wrapped in a span) or a file-type icon for a skill.
 */
export function SkillVisual({ name, emoji, emojiClassName }: SkillVisualProps) {
  if (emoji) {
    return <span className={emojiClassName}>{emoji}</span>;
  }
  return <>{getFileIcon(name)}</>;
}
