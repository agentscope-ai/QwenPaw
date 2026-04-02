import { getApiUrl, clearAuthToken } from "./config";
import { buildAuthHeaders } from "./authHeaders";

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

function buildHeaders(method?: string, extra?: HeadersInit): Headers {
  // Normalize extra to a Headers instance for consistent handling
  const headers = extra instanceof Headers ? extra : new Headers(extra);

  // Only add Content-Type for methods that typically have a body
  if (method && ["POST", "PUT", "PATCH"].includes(method.toUpperCase())) {
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

export async function request<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const url = getApiUrl(path);
  const method = options.method || "GET";
  const headers = buildHeaders(method, options.headers);

  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (!response.ok) {
    // Handle 401: clear token and redirect to login
    if (!response.ok) {
      // Handle 401: clear token and redirect to login
      if (response.status === 401) {
        clearAuthToken();
        if (window.location.pathname !== "/login") {
          window.location.href = "/login";
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

    const text = await response.text().catch(() => "");
    const contentType = response.headers.get("content-type") || "";
    const errorMessage = getErrorMessageFromBody(text, contentType);
    throw new Error(
      errorMessage ||
        `Request failed: ${response.status} ${response.statusText}`,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    // This should not happen for API endpoints - treat as error
    const text = await response.text();
    throw new Error(
      `Expected JSON response from ${url} but got content-type: ${contentType}. Body: ${text.substring(
        0,
        200,
      )}`,
    );
  }

  return (await response.json()) as T;
}
