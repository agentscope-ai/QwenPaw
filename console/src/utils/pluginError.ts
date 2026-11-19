import type { TFunction } from "i18next";

/** Explain shared dependency failures while preserving other plugin messages. */
export function pluginErrorMessage(
  error: unknown,
  fallback: string,
  t: TFunction,
): string {
  const message =
    typeof error === "string"
      ? error
      : error instanceof Error
      ? error.message
      : "";
  const declaredCode =
    error && typeof error === "object" && "code" in error ? error.code : null;
  const code =
    typeof declaredCode === "string"
      ? declaredCode
      : message.match(/\bDEPENDENCY_[A-Z_]+\b/)?.[0];
  if (!code?.startsWith("DEPENDENCY_")) return message || fallback;

  if (code === "DEPENDENCY_ENVIRONMENT_AMBIGUOUS")
    return t("pluginManager.dependencyErrors.ambiguous");
  if (code === "DEPENDENCY_METADATA_INVALID")
    return t("pluginManager.dependencyErrors.invalidMetadata");

  const detail = message.startsWith(code)
    ? message
        .slice(code.length)
        .replace(/^[:\s]+/, "")
        .trim()
    : message;
  if (detail) return detail;

  return t("pluginManager.dependencyErrors.failed");
}
