export function resolveLanguage(lang?: string, className?: string): string {
  const explicit = lang?.trim().split(/\s+/, 1)[0];
  const fromClassName = className?.match(/(?:^|\s)language-([^\s]+)/)?.[1];
  return (explicit || fromClassName || "").toLowerCase();
}
