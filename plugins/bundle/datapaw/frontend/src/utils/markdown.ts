/**
 * Strip YAML frontmatter from the beginning of a markdown string.
 *
 * Many .md files start with a YAML header wrapped in `---` delimiters.
 * marked / XMarkdown renders `---` as <hr> and the YAML body as plain text.
 * This helper removes the frontmatter block before passing content to the renderer.
 */
export const stripFrontmatter = (s: string): string =>
  s.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "");
