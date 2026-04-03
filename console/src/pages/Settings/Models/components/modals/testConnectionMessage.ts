import type { TFunction } from "i18next";
import type { TestConnectionResponse } from "../../../../../api/types";

const FAILURE_PREFIX_PATTERNS = [
  /^Connection failed:\s*/i,
  /^Model connection failed:\s*/i,
];

const GENERIC_FAILURE_MESSAGES = new Set([
  "connection failed",
  "model connection failed",
]);

function normalizeFailureMessage(message: string): string {
  return message.toLowerCase().trim().replace(/\.+$/, "");
}

function isGenericFailureMessage(message: string): boolean {
  return GENERIC_FAILURE_MESSAGES.has(normalizeFailureMessage(message));
}

export function getTestConnectionFailureDetail(
  message?: string | null,
): string | null {
  const trimmed = message?.trim();
  if (!trimmed || isGenericFailureMessage(trimmed)) {
    return null;
  }

  for (const pattern of FAILURE_PREFIX_PATTERNS) {
    if (pattern.test(trimmed)) {
      const detail = trimmed.replace(pattern, "").trim();
      return detail && !isGenericFailureMessage(detail) ? detail : null;
    }
  }

  return trimmed;
}

export function getLocalizedTestConnectionMessage(
  result: Pick<TestConnectionResponse, "success" | "message">,
  t: TFunction,
): string {
  if (result.success) {
    return t("models.testConnectionSuccess");
  }

  const detail = getTestConnectionFailureDetail(result.message);
  return detail
    ? t("models.testConnectionFailedWithMessage", { message: detail })
    : t("models.testConnectionFailed");
}
