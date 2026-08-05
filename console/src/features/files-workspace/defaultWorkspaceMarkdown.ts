export const DEFAULT_WORKSPACE_MARKDOWN_FILENAMES = [
  "AGENTS.md",
  "SOUL.md",
  "PROFILE.md",
  "MEMORY.md",
  "HEARTBEAT.md",
  "BOOTSTRAP.md",
] as const;

const defaultWorkspaceMarkdownFilenames = new Set<string>(
  DEFAULT_WORKSPACE_MARKDOWN_FILENAMES,
);

export function isDefaultWorkspaceMarkdown(filename: string): boolean {
  return defaultWorkspaceMarkdownFilenames.has(filename);
}
