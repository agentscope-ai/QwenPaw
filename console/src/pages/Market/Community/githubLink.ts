/**
 * Optional post-level GitHub repository link (Platform `github_link`).
 * Mirrors the Platform rule: a public github.com/{owner}/{repo} URL. The
 * server side cannot be trusted to normalize, so every value crossing a
 * boundary (submit, render) is canonicalized locally.
 */
const GITHUB_REPO_RE =
  /^(?:https?:\/\/)?(?:www\.)?github\.com\/([\w.-]+)\/([\w.-]+?)(?:\.git)?\/?$/i;

/** True when the value parses as a public GitHub repository URL. */
export function isGithubRepoLink(value: string): boolean {
  return GITHUB_REPO_RE.test(value.trim());
}

/**
 * Canonical https://github.com/{owner}/{repo} form of a repository link.
 * Empty or unparsable values collapse to "" so callers can never leak a
 * scheme-less href (resolved as same-origin) or a non-GitHub destination.
 */
export function normalizeGithubLink(value: string): string {
  const match = value.trim().match(GITHUB_REPO_RE);
  if (!match) return "";
  return `https://github.com/${match[1]}/${match[2]}`;
}
