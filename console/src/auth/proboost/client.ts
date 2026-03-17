import { getStoredAuthToken } from "../storage";
import { getApiUrl } from "../../api/config";
import {
  FALLBACK_AUTH_META,
  normalizeCountryCode,
  normalizeSupportedCountryCodes,
} from "./config";
import type {
  ProBoostCountryCodeOption,
  ProBoostAuthMeta,
  PasswordLoginPayload,
  ProBoostAuthData,
  ProBoostResponse,
  SendSmsCodePayload,
  VerifySmsCodePayload,
} from "./types";

function formatProBoostErrorMessage(
  msg?: string | null,
  code?: string | null,
): string {
  const text = msg?.trim() || "Request failed";
  if (code && code !== "0") {
    return `${text} (code: ${code})`;
  }
  return text;
}

function buildHeaders(): Headers {
  const headers = new Headers({
    "Content-Type": "application/json",
  });

  const token = getStoredAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

export function parseAuthMeta(data: unknown): ProBoostAuthMeta {
  if (!data || typeof data !== "object") {
    throw new Error("Invalid ProBoost auth metadata");
  }

  const record = data as Record<string, unknown>;
  const supportedCountryCodes = normalizeSupportedCountryCodes(
    Array.isArray(record.supportedCountryCodes)
      ? record.supportedCountryCodes.filter(
          (value): value is string => typeof value === "string",
        )
      : FALLBACK_AUTH_META.supportedCountryCodes,
  );

  const rawOptions = Array.isArray(record.countryCodeOptions)
    ? record.countryCodeOptions
    : [];

  const optionMap = new Map<string, ProBoostCountryCodeOption>();
  for (const item of rawOptions) {
    if (!item || typeof item !== "object") {
      continue;
    }

    const optionRecord = item as Record<string, unknown>;
    if (typeof optionRecord.value !== "string") {
      continue;
    }

    const value = optionRecord.value.trim();
    if (!value || optionMap.has(value)) {
      continue;
    }

    optionMap.set(value, {
      value,
      labelKey:
        typeof optionRecord.labelKey === "string" && optionRecord.labelKey.trim()
          ? optionRecord.labelKey.trim()
          : undefined,
    });
  }

  const countryCodeOptions = supportedCountryCodes.map(
    (value) => optionMap.get(value) ?? { value },
  );

  return {
    defaultCountryCode: normalizeCountryCode(
      typeof record.defaultCountryCode === "string"
        ? record.defaultCountryCode
        : FALLBACK_AUTH_META.defaultCountryCode,
      supportedCountryCodes,
    ),
    supportedCountryCodes,
    countryCodeOptions,
  };
}

export async function fetchAuthMeta(): Promise<ProBoostAuthMeta> {
  const response = await fetch(getApiUrl("/proboost-auth/meta"), {
    method: "GET",
    credentials: "include",
  });

  const json = (await response.json().catch(() => null)) as unknown;

  if (!response.ok || !json) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }

  return parseAuthMeta(json);
}

async function postJson<T>(path: string, body: unknown): Promise<ProBoostResponse<T>> {
  const response = await fetch(getApiUrl(path), {
    method: "POST",
    headers: buildHeaders(),
    body: JSON.stringify(body),
    credentials: "include",
  });

  const json = (await response.json().catch(() => null)) as
    | ProBoostResponse<T>
    | null;

  if (!response.ok || !json) {
    throw new Error(
      json
        ? formatProBoostErrorMessage(json.msg, json.code)
        : `Request failed: ${response.status} ${response.statusText}`,
    );
  }

  if (!json.success || json.code !== "0") {
    throw new Error(formatProBoostErrorMessage(json.msg, json.code));
  }

  return json;
}

export function loginWithPassword(payload: PasswordLoginPayload) {
  return postJson<ProBoostAuthData>("/proboost-auth/login", payload);
}

export function sendSmsCode(payload: SendSmsCodePayload) {
  return postJson<boolean>("/proboost-auth/send-sms-code", payload);
}

export function verifySmsCode(payload: VerifySmsCodePayload) {
  return postJson<ProBoostAuthData>("/proboost-auth/verify-sms-code", payload);
}


