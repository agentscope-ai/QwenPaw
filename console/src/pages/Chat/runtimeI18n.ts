import i18n from "../../i18n";

const RUNTIME_I18N_PREFIX = "__copaw_i18n__:";

interface RuntimeI18nPayload {
  key: string;
  values?: Record<string, unknown>;
}

function localizeRuntimeText(text: string): string {
  if (!text.startsWith(RUNTIME_I18N_PREFIX)) {
    return text;
  }

  try {
    const payload = JSON.parse(
      text.slice(RUNTIME_I18N_PREFIX.length),
    ) as RuntimeI18nPayload;
    if (!payload?.key) {
      return text;
    }
    if (!i18n.exists(payload.key)) {
      return payload.key;
    }
    return i18n.t(payload.key, payload.values ?? {});
  } catch {
    return text;
  }
}

export function localizeRuntimeValue<T>(value: T): T {
  if (typeof value === "string") {
    return localizeRuntimeText(value) as T;
  }
  if (Array.isArray(value)) {
    return value.map((item) => localizeRuntimeValue(item)) as T;
  }
  if (!value || typeof value !== "object") {
    return value;
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, item]) => [
      key,
      localizeRuntimeValue(item),
    ]),
  ) as T;
}

export function parseRuntimeResponseChunk(chunk: unknown): unknown {
  if (typeof chunk !== "string") {
    return chunk;
  }
  return localizeRuntimeValue(JSON.parse(chunk));
}
