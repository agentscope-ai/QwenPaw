import type { editor as MonacoEditor } from "monaco-editor";

type CopyMode = "whole-file" | "lines-only" | "with-code";

const stripTrailingNewlines = (value: string) => value.replace(/\n+$/, "");

export function getEditorLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const languages: Record<string, string> = {
    py: "python",
    ts: "typescript",
    tsx: "typescript",
    js: "javascript",
    jsx: "javascript",
    json: "json",
    yaml: "yaml",
    yml: "yaml",
    md: "markdown",
    sh: "shell",
    bash: "shell",
    html: "html",
    css: "css",
    less: "less",
    scss: "scss",
    sql: "sql",
    toml: "ini",
    rs: "rust",
    go: "go",
    java: "java",
    cpp: "cpp",
    c: "c",
    h: "c",
    kt: "kotlin",
    rb: "ruby",
  };
  return languages[ext] ?? "plaintext";
}

export function visibleEditorPath(path: string): string {
  return path.includes("::") ? path.slice(path.indexOf("::") + 2) : path;
}

export function detectCopyMode(
  selection: {
    startLineNumber: number;
    startColumn: number;
    endLineNumber: number;
    endColumn: number;
  },
  model: MonacoEditor.ITextModel,
): {
  mode: CopyMode;
  code: string;
  startLine: number;
  endLine: number;
} {
  const code = model.getValueInRange(selection);
  const startLine = selection.startLineNumber;
  let endLine = selection.endLineNumber;
  if (endLine > startLine && selection.endColumn === 1) {
    endLine -= 1;
  }

  const lines: string[] = [];
  for (let line = startLine; line <= endLine; line += 1) {
    lines.push(model.getLineContent(line));
  }
  if (stripTrailingNewlines(code) === lines.join("\n")) {
    return { mode: "lines-only", code, startLine, endLine };
  }

  return { mode: "with-code", code, startLine, endLine };
}

export function formatSelectionForChat(
  filePath: string,
  code: string,
  startLine: number,
  endLine: number,
  mode: CopyMode,
): string {
  const displayPath = visibleEditorPath(filePath);
  if (mode === "whole-file") {
    return displayPath;
  }
  const lineRange =
    startLine === endLine ? `${startLine}` : `${startLine}-${endLine}`;
  if (mode === "lines-only") {
    return `${displayPath}:${lineRange}`;
  }
  const language = getEditorLanguage(filePath);
  return `${displayPath}:${lineRange}\n\`\`\`${language}\n${code}\n\`\`\``;
}
