/**
 * Extension → Monaco language id mapping for the Coding editor.
 * Shared by the normal editor and the DiffEditor in TabbedEditor.
 */

export function getLanguage(path: string): string {
  const ext = path.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
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
    robot: "robotframework",
    resource: "robotframework",
  };
  return map[ext] ?? "plaintext";
}
