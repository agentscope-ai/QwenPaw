import {
  Calendar,
  Code2,
  File,
  FileImage,
  FileSpreadsheet,
  FileText,
  FileType2,
  FileVideo,
  FileArchive,
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
    "browser_visible",
    "guidance",
    "himalaya",
    "dingtalk_channel",
  ]);

  if (textSkillIcons.has(skillKey)) {
    return <FileText size={16} className="text-[#1890ff]" />;
  }

  switch (skillKey) {
    case "docx":
      return <FileType2 size={16} className="text-[#2B8DFF]" />;
    case "xlsx":
      return <FileSpreadsheet size={16} className="text-[#44C161]" />;
    case "pptx":
      return <FileVideo size={16} className="text-[#FF5B3B]" />;
    case "pdf":
      return <File size={16} className="text-[#F04B57]" />;
    case "cron":
      return <Calendar size={16} className="text-[#13c2c2]" />;
    default:
      break;
  }

  const extension = filePath.split(".").pop()?.toLowerCase() || "";

  switch (extension) {
    case "txt":
    case "md":
    case "markdown":
      return <FileText size={16} className="text-[#1890ff]" />;
    case "zip":
    case "rar":
    case "7z":
    case "tar":
    case "gz":
      return <FileArchive size={16} className="text-[#fa8c16]" />;
    case "pdf":
      return <File size={16} className="text-[#F04B57]" />;
    case "doc":
    case "docx":
      return <FileType2 size={16} className="text-[#2B8DFF]" />;
    case "xls":
    case "xlsx":
      return <FileSpreadsheet size={16} className="text-[#44C161]" />;
    case "ppt":
    case "pptx":
      return <FileVideo size={16} className="text-[#FF5B3B]" />;
    case "jpg":
    case "jpeg":
    case "png":
    case "gif":
    case "svg":
    case "webp":
      return <FileImage size={16} className="text-[#eb2f96]" />;
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
      return <Code2 size={16} className="text-[#52c41a]" />;
    default:
      return <FileText size={16} className="text-[#1890ff]" />;
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
