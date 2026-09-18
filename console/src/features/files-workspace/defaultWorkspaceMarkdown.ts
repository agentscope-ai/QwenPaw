export const DEFAULT_WORKSPACE_MARKDOWN_FILENAMES = [
  "AGENTS.md",
  "SOUL.md",
  "PROFILE.md",
  "MEMORY.md",
  "HEARTBEAT.md",
  "BOOTSTRAP.md",
] as const;

export function isWorkspaceMarkdown(filename: string): boolean {
  return filename.endsWith(".md");
}
