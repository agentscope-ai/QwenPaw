import { createStreamingParser } from "@openuidev/react-lang";
import { openuiLibrary } from "@openuidev/react-ui";

/** Commit complete constructs, not partially written component props.
 * Forward references remain legal while streaming, so each defined component
 * can appear before the rest of the program. Syntax stays owned by OpenUI.
 */
export function createUIStream() {
  const parser = createStreamingParser(openuiLibrary.toJSONSchema());
  let displayed = "";
  return (source: string, isStreaming: boolean) => {
    // Markdown adds a trailing newline to partial code nodes. Ignore that
    // terminator when distinguishing an append from a replacement.
    if (!source.trimEnd().startsWith(displayed.trimEnd())) displayed = "";
    try {
      const result = parser.set(source, !isStreaming);
      const prohibited =
        result.queryStatements.length > 0 ||
        result.mutationStatements.length > 0;
      const invalid = result.meta.errors.some(
        (error) => error.severity !== "warning",
      );
      const complete =
        !!(result.root || result.rootExpression) &&
        !result.meta.incomplete &&
        !invalid;
      if (
        prohibited ||
        (!isStreaming && (!complete || result.meta.unresolved.length > 0))
      ) {
        return { response: "", error: true };
      }
      if (complete) displayed = source;
      return { response: displayed, error: false };
    } catch {
      return { response: isStreaming ? displayed : "", error: !isStreaming };
    }
  };
}
