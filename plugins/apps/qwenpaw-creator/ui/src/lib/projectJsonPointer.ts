function escapeJsonPointerSegment(value: string | number): string {
  return String(value).replace(/~/g, "~0").replace(/\//g, "~1");
}

/** Build an RFC 6901 pointer to the canonical field in project.json. */
export function projectJsonPointer(
  ...segments: Array<string | number>
): string {
  return `/${segments.map(escapeJsonPointerSegment).join("/")}`;
}

/** Semantic selection anchor, with the exact JSON pointer kept separately. */
export function creatorFieldForPointer(pointer: string): string {
  const parts = pointer
    .split("/")
    .slice(1)
    .map((part) => part.replace(/~1/g, "/").replace(/~0/g, "~"));
  if (parts[0] === "visual" && parts[2] === "items") {
    return `${parts[1] === "cast_lineups" ? "lineup" : "asset"}:${
      parts[3]
    }/${parts.slice(4).join("/")}`;
  }
  if (parts[0] === "timelines" && parts[3] === "elements_by_id") {
    return `element:${parts[4]}/${parts.slice(5).join("/")}`;
  }
  return `project/${parts.join("/")}`;
}
