import type { DisplayPart } from "../../api/types";

export interface CollapsedParts {
  collapsible: boolean;
  parts: DisplayPart[];
}

export function collapseTextParts(
  parts: DisplayPart[],
  limit = 700,
): CollapsedParts {
  const textLength = parts.reduce(
    (total, part) => total + (part.type === "text" ? part.text.length : 0),
    0,
  );
  if (textLength <= limit) return { collapsible: false, parts };

  let remaining = limit;
  let truncated = false;
  const preview = parts.flatMap((part): DisplayPart[] => {
    if (part.type !== "text") return [part];
    if (remaining <= 0) return [];
    if (part.text.length <= remaining) {
      remaining -= part.text.length;
      return [part];
    }
    const text = part.text.slice(0, remaining).trimEnd();
    remaining = 0;
    truncated = true;
    return text ? [{ type: "text", text: `${text}…` }] : [];
  });
  if (!truncated) {
    const lastText = preview.findLastIndex((part) => part.type === "text");
    if (lastText >= 0 && preview[lastText].type === "text") {
      preview[lastText] = {
        type: "text",
        text: `${preview[lastText].text.trimEnd()}…`,
      };
    }
  }
  return { collapsible: true, parts: preview };
}
