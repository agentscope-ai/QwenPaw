function escapeJsonPointerSegment(value: string | number): string {
  return String(value).replace(/~/g, "~0").replace(/\//g, "~1");
}

/** Build an RFC 6901 pointer to the canonical field in project.json. */
export function projectJsonPointer(
  ...segments: Array<string | number>
): string {
  return `/${segments.map(escapeJsonPointerSegment).join("/")}`;
}
