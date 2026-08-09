import type { LoopModeInfo } from "../../stores/loopStore";
import { resolveLoopModeDescriptionMarkdown } from "../../utils/loopModeDescription";

export interface LoopSlashSuggestion {
  command: string;
  value: string;
  /** First-line Markdown; render with InlineMarkdown in the suggestion label. */
  description: string;
}

export function buildLoopSlashSuggestions(
  modes: LoopModeInfo[],
  reservedCommands: ReadonlySet<string>,
  t: (key: string) => string,
  lang: string = "en",
): LoopSlashSuggestion[] {
  return modes
    .filter(
      (mode) =>
        Boolean(mode.slash_command) &&
        !reservedCommands.has(mode.slash_command),
    )
    .map((mode) => ({
      command: `/${mode.slash_command}`,
      value: mode.slash_command,
      description: resolveLoopModeDescriptionMarkdown(mode, t, lang),
    }));
}
