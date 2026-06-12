import type { TFunction } from "i18next";
import type {
  DataSourceRecord,
  DataSourceTestResult,
} from "../../../api/types/dataSource";

export function resolveApiErrorCode(
  error: unknown,
  fallback = "deleteFailed",
): string {
  if (error instanceof Error) {
    const idx = error.message.indexOf(" - ");
    return idx === -1 ? error.message : error.message.slice(0, idx);
  }
  return fallback;
}

/** Map API `detail` / `message` codes; fall back to raw text for server messages. */
export function resolveErrorMessage(
  t: (key: string) => string,
  code: string,
  fallbackKey?: string,
): string {
  const key = `dataConnection.errors.${code}`;
  const translated = t(key);
  if (translated !== key) {
    return translated;
  }
  if (fallbackKey) {
    const fallback = t(fallbackKey);
    if (fallback !== fallbackKey) {
      return fallback;
    }
  }
  return code;
}

/** POST /test success: { success: true, message, latencyMs } */
export function formatTestSuccessMessage(
  t: TFunction,
  result: DataSourceTestResult,
): string {
  return t("dataConnection.testSuccess", {
    message: resolveErrorMessage(t, result.message),
    latency: result.latencyMs ?? 0,
  });
}

/** POST / success: DataSourceRecord */
export function formatCreateSuccessMessage(
  t: TFunction,
  record: DataSourceRecord,
): string {
  return t("dataConnection.addSuccessWithName", { name: record.name });
}
