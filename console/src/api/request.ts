import { getApiAuthMode, getApiUrl } from "./config";
import { buildAuthHeaders } from "./authHeaders";
import {
  clearAccessSession,
  getAccessSessionGeneration,
  refreshAccessSession,
} from "./authSession";
import { getLoginHref, isLoginPath } from "../utils/navigationMode";

function getErrorMessageFromBody(
  text: string,
  contentType: string,
): string | null {
  if (!text) {
    return null;
  }

  if (!contentType.includes("application/json")) {
    return text;
  }

  try {
    const payload = JSON.parse(text) as {
      detail?: unknown;
      message?: unknown;
      error?: unknown;
    };

    if (typeof payload.detail === "string" && payload.detail) {
      return payload.detail;
    }
    if (typeof payload.message === "string" && payload.message) {
      return payload.message;
    }
    if (typeof payload.error === "string" && payload.error) {
      return payload.error;
    }
  } catch {
    return text;
  }

  return text;
}

function buildHeaders(
  method?: string,
  extra?: HeadersInit,
  body?: BodyInit | null,
): Headers {
  // Normalize extra to a Headers instance for consistent handling
  const headers = new Headers(extra);

  // Only add Content-Type for methods that typically have a body
  if (
    method &&
    ["POST", "PUT", "PATCH"].includes(method.toUpperCase()) &&
    !(body instanceof FormData)
  ) {
    // Don't override if caller explicitly set Content-Type
    if (!headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
  }

  for (const [key, value] of Object.entries(buildAuthHeaders())) {
    if (!headers.has(key)) {
      headers.set(key, value);
    }
  }

  return headers;
}

export interface RequestOptions extends RequestInit {
  /** Request timeout in milliseconds. Defaults to 30000 (30 seconds). */
  timeout?: number;
  /** Number of retry attempts on timeout. Defaults to 0 (no retry). */
  retries?: number;
  /** Delay between retries in milliseconds. Defaults to 1000 (1 second). */
  retryDelay?: number;
}

const DEFAULT_TIMEOUT_MS = 30000;
const DEFAULT_RETRIES = 0;
const DEFAULT_RETRY_DELAY_MS = 1000;

export async function request<T = unknown>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const url = getApiUrl(path);
  const method = options.method || "GET";
  const {
    timeout = DEFAULT_TIMEOUT_MS,
    retries = DEFAULT_RETRIES,
    retryDelay = DEFAULT_RETRY_DELAY_MS,
    signal: callerSignal,
    ...fetchOptions
  } = options;

  // Early exit: caller's signal already aborted before we even start
  if (callerSignal?.aborted) {
    throw new DOMException("The operation was aborted", "AbortError");
  }

  const sessionGeneration = getAccessSessionGeneration();
  const authMode = getApiAuthMode();
  const assertAuthenticationCurrent = () => {
    if (
      sessionGeneration !== getAccessSessionGeneration() ||
      authMode !== getApiAuthMode() ||
      callerSignal?.aborted
    ) {
      throw new DOMException("Authentication context changed", "AbortError");
    }
  };

  let lastError: Error | null = null;
  let authRetried = false;

  for (let attempt = 0; attempt <= retries; attempt++) {
    // Create AbortController for timeout handling
    const controller = new AbortController();
    let timedOut = false;
    const timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeout);

    // Wire caller's signal to our controller so external abort also works
    let onCallerAbort: (() => void) | undefined;
    if (callerSignal) {
      if (callerSignal.aborted) {
        controller.abort();
      } else {
        onCallerAbort = () => controller.abort();
        callerSignal.addEventListener("abort", onCallerAbort, { once: true });
      }
    }

    try {
      let response: Response;
      while (true) {
        assertAuthenticationCurrent();
        if (controller.signal.aborted) {
          throw new DOMException("The operation was aborted", "AbortError");
        }
        response = await fetch(url, {
          ...fetchOptions,
          headers: buildHeaders(method, options.headers, fetchOptions.body),
          signal: controller.signal,
        });
        if (controller.signal.aborted) {
          throw new DOMException("The operation was aborted", "AbortError");
        }
        assertAuthenticationCurrent();
        if (
          response.status !== 401 ||
          authRetried ||
          getApiAuthMode() !== "multi_user"
        ) {
          break;
        }
        authRetried = true;
        const refreshed = await refreshAccessSession();
        assertAuthenticationCurrent();
        if (controller.signal.aborted)
          throw new DOMException("The operation was aborted", "AbortError");
        if (!refreshed) break;
      }

      if (!response.ok) {
        if (response.status === 401) {
          assertAuthenticationCurrent();
          clearAccessSession();
          if (!isLoginPath(window.location.pathname)) {
            window.location.href = getLoginHref(window.location);
          }
          throw new Error("Not authenticated");
        }

        const text = await response.text().catch(() => "");
        const contentType = response.headers.get("content-type") || "";
        const errorMessage = getErrorMessageFromBody(text, contentType);

        // Preserve raw body for parseErrorDetail() to extract structured fields
        const finalMessage = errorMessage
          ? `${errorMessage} - ${text}`
          : `Request failed: ${response.status} ${response.statusText}`;

        throw new Error(finalMessage);
      }

      if (response.status === 204) {
        return undefined as T;
      }

      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        return (await response.text()) as unknown as T;
      }

      return (await response.json()) as T;
    } catch (error) {
      if (
        error instanceof DOMException &&
        error.name === "AbortError" &&
        !timedOut
      ) {
        // External abort (caller cancelled): do not retry, rethrow as-is
        throw error;
      }

      if (error instanceof DOMException && error.name === "AbortError") {
        // Timeout-triggered abort
        lastError = new Error(
          `Request timeout after ${timeout}ms: ${method} ${path}`,
        );

        // Retry if we have attempts remaining
        if (attempt < retries) {
          await new Promise((resolve) => setTimeout(resolve, retryDelay));
          continue;
        }
      } else {
        // Non-timeout errors should not retry
        throw error;
      }
    } finally {
      clearTimeout(timeoutId);
      if (onCallerAbort && callerSignal) {
        callerSignal.removeEventListener("abort", onCallerAbort);
      }
    }
  }

  // All retries exhausted
  throw lastError;
}
