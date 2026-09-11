import type { LoopModeInfo } from "../stores/loopStore";
import { resolveLocalizedText } from "./resolveLocalizedText";

/**
 * First non-empty line of loop/plugin help text, Markdown markers preserved.
 *
 * OMP CommandSpec.help_text is a multi-line Markdown doc; menus only need the
 * summary line, which is then rendered with restricted inline Markdown.
 */
export function firstLoopDescriptionMarkdown(description?: string): string {
  if (!description) return "";
  return (
    description
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => line.length > 0) ?? ""
  );
}

/**
 * Builtin modes use Console i18n; plugins prefer description_i18n + lang,
 * then fall back to API description.
 */
export function resolveLoopModeDescriptionMarkdown(
  mode: Pick<
    LoopModeInfo,
    "id" | "source" | "description" | "description_i18n"
  >,
  t: (key: string) => string,
  lang: string = "en",
): string {
  if (mode.source === "builtin") {
    return firstLoopDescriptionMarkdown(t(`loop.modes.${mode.id}.description`));
  }
  const fromI18n = resolveLocalizedText(mode.description_i18n, lang);
  return firstLoopDescriptionMarkdown(fromI18n || mode.description);
}

/** Plugin name_i18n when present; otherwise API / builtin name via t. */
export function resolveLoopModeName(
  mode: Pick<LoopModeInfo, "id" | "name" | "source" | "name_i18n">,
  t: (key: string) => string,
  lang: string = "en",
): string {
  if (mode.source === "builtin") {
    return t(`loop.modes.${mode.id}.name`);
  }
  return resolveLocalizedText(mode.name_i18n, lang) || mode.name;
}
