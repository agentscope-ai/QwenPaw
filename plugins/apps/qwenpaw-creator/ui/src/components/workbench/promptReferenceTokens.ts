import type { PromptRichToken } from "./PromptRichBlock";

/** Never guess when a reference index is missing, invalid, or ambiguous. */
export function promptTokenAt(
  tokens: PromptRichToken[],
  index: number,
): PromptRichToken | null {
  if (!Number.isSafeInteger(index) || index < 1) return null;
  const matches = tokens.filter((token) => token.index === index);
  return matches.length === 1 && !matches[0].missing ? matches[0] : null;
}

/** Compare the actual reference bindings while an editor owns a local draft.
 * Signed thumbnail URLs and public-name refreshes do not change a known id. */
export function promptReferenceSignature(tokens: PromptRichToken[]): string {
  return JSON.stringify(
    tokens
      .map((token) => ({
        index: token.index,
        identity:
          token.referenceId ??
          `${token.kind}\u0000${token.name}\u0000${token.thumbUrl ?? ""}`,
        missing: Boolean(token.missing),
      }))
      .sort((a, b) => a.index - b.index),
  );
}
