import type { ProjectDocument } from "@/contracts/creator";

/** Resolve known entity references in descriptive prose, without changing image
 * indexes or literal dialogue, URLs and code. This never invents a reference. */
export function presentPromptEntityNames(
  value: string,
  project: ProjectDocument | null | undefined,
): string {
  const names = new Map<string, string>();
  const entities = project?.visual?.entities?.items ?? {};
  for (const [id, entity] of Object.entries(entities)) {
    const name = entity.name?.trim();
    if (!id.includes(":") || !name || name in entities) continue;
    names.set(id, name);
    names.set(`visual-entity:${id}`, name);
  }
  if (!names.size) return value;
  const protectedRanges: Array<[number, number]> = Array.from(
    value.matchAll(
      /[A-Za-z][A-Za-z0-9+.-]*:\/\/[^\s<>"'“”‘’「」『』]*|`+[^`\n]*`+|“[^”]*”|‘[^’]*’|「[^」]*」|『[^』]*』|"(?:\\.|[^"\\])*"|(?<![A-Za-z0-9])'(?:\\.|[^'\\])*'|《[^》]*》|@[A-Za-z0-9_:.-]+/gu,
    ),
    (match) => [match.index, match.index + match[0].length],
  );
  let fence: { char: string; length: number } | null = null;
  let offset = 0;
  for (const line of value.split("\n")) {
    const marker = /^\s*(`{3,}|~{3,})/u.exec(line)?.[1];
    if (marker) {
      if (!fence) fence = { char: marker[0], length: marker.length };
      else if (marker[0] === fence.char && marker.length >= fence.length)
        fence = null;
      protectedRanges.push([offset, offset + line.length]);
    } else if (
      fence ||
      /^(?: {4}|\t)/u.test(line) ||
      /^\s*(?:台词|对白|字幕|旁白|Dialogue|Caption|Narration)\s*[：:]/iu.test(
        line,
      )
    ) {
      protectedRanges.push([offset, offset + line.length]);
    }
    offset += line.length + 1;
  }
  const tokens = [...names.keys()]
    .sort((a, b) => b.length - a.length)
    .map((id) => id.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"))
    .join("|");
  const matcher = new RegExp(
    `(?<![A-Za-z0-9_:./\\\\@-])(?:${tokens})(?![A-Za-z0-9_:./\\\\@-])`,
    "gu",
  );
  // Match against the original text so an adjacent protected @mention cannot
  // turn a compound entity@variant reference into a standalone entity token.
  return value.replace(matcher, (token: string, start: number) =>
    protectedRanges.some(
      ([from, to]) => start < to && start + token.length > from,
    )
      ? token
      : names.get(token)!,
  );
}
