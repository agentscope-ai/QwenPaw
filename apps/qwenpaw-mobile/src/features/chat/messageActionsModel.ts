import type { DisplayPart } from "../../api/types";

export function messageText(parts: DisplayPart[]): string {
  return parts
    .filter((part): part is Extract<DisplayPart, { type: "text" }> => (
      part.type === "text" && Boolean(part.text.trim())
    ))
    .map((part) => part.text.trim())
    .join("\n\n");
}
