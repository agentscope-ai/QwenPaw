function escapeJsonPointerSegment(value: string | number): string {
  return String(value).replace(/~/g, "~0").replace(/\//g, "~1");
}

/** Build an RFC 6901 pointer to the canonical field in project.json. */
export function projectJsonPointer(
  ...segments: Array<string | number>
): string {
  return `/${segments.map(escapeJsonPointerSegment).join("/")}`;
}

/** Result of reading one RFC 6901 pointer against a project document. */
export interface ProjectPointerRead {
  /** True when every token resolved; false when the field is absent. */
  present: boolean;
  value: unknown;
}

/**
 * Read the value at an RFC 6901 pointer.
 *
 * Mirrors the resolver used by inline review diffs so a card can show and
 * CAS-patch the exact field it points at. `present` distinguishes an absent
 * field (patch with op "add") from a present one (patch with op "replace").
 */
export function readProjectPointer(
  root: unknown,
  pointer: string,
): ProjectPointerRead {
  const absent: ProjectPointerRead = { present: false, value: undefined };
  if (!pointer.startsWith("/")) return absent;
  const tokens = pointer
    .slice(1)
    .split("/")
    .map((token) => token.replace(/~1/g, "/").replace(/~0/g, "~"));
  let current: unknown = root;
  for (const token of tokens) {
    if (Array.isArray(current)) {
      if (!/^(0|[1-9][0-9]*)$/.test(token)) return absent;
      const index = Number(token);
      if (index >= current.length) return absent;
      current = current[index];
    } else if (current !== null && typeof current === "object") {
      const record = current as Record<string, unknown>;
      if (!Object.prototype.hasOwnProperty.call(record, token)) return absent;
      current = record[token];
    } else {
      return absent;
    }
  }
  return { present: true, value: current };
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
