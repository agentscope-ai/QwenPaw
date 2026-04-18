import type { TFunction } from "i18next";
import type { BuiltinUpdateNotice } from "../../../api/types";

function getNoticeNames(items: Array<{ name: string }> | undefined): string[] {
  return (items || [])
    .map((item) => String(item.name || "").trim())
    .filter(Boolean);
}

export function getBuiltinNoticeLines(
  notice: BuiltinUpdateNotice | null,
  t: TFunction,
): string[] {
  if (!notice?.has_updates) return [];

  const lines: string[] = [];
  const addedNames = getNoticeNames(notice.added);
  const missingNames = getNoticeNames(notice.missing);
  const updatedNames = getNoticeNames(notice.updated);
  const removedNames = getNoticeNames(notice.removed);

  if (addedNames.length > 0) {
    lines.push(
      t("skillPool.builtinNoticeLineAdded", {
        names: addedNames.join(", "),
      }),
    );
  }
  if (missingNames.length > 0) {
    lines.push(
      t("skillPool.builtinNoticeLineMissing", {
        names: missingNames.join(", "),
      }),
    );
  }
  if (updatedNames.length > 0) {
    lines.push(
      t("skillPool.builtinNoticeLineUpdated", {
        names: updatedNames.join(", "),
      }),
    );
  }
  if (removedNames.length > 0) {
    lines.push(
      t("skillPool.builtinNoticeLineRemoved", {
        names: removedNames.join(", "),
      }),
    );
  }

  return lines;
}
