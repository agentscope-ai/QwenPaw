import { File, FileCode2, FileText } from "lucide-react";

interface FileGlyphProps {
  name: string;
  size?: number;
}

export default function FileGlyph({ name, size = 15 }: FileGlyphProps) {
  const extension = name.split(".").pop()?.toLowerCase();
  if (["md", "mdx", "txt", "log", "csv"].includes(extension ?? "")) {
    return <FileText size={size} />;
  }
  if (
    [
      "py",
      "ts",
      "tsx",
      "js",
      "jsx",
      "go",
      "rs",
      "java",
      "html",
      "css",
    ].includes(extension ?? "")
  ) {
    return <FileCode2 size={size} />;
  }
  return <File size={size} />;
}
