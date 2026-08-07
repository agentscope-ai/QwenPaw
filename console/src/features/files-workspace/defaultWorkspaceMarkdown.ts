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

/**
 * Whether `filename` is one of the built-in workspace Markdown files. Used
 * where the curated default set is required (e.g. the system-prompt profile
 * picker), as opposed to `isWorkspaceMarkdown`, which accepts any Markdown.
 */
export function isDefaultWorkspaceMarkdown(filename: string): boolean {
  return defaultWorkspaceMarkdownFilenames.has(filename);
}

/**
 * Whether `filename` is a workspace Markdown file, including user-created ones.
 */
export function isWorkspaceMarkdown(filename: string): boolean {
  return filename.endsWith(".md");
}
