import { getApiUrl, getApiToken } from "./config";

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

  // Add authorization token if available
  const token = getApiToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
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
    const text = await response.text().catch(() => "");
    throw new Error(
      `Request failed: ${response.status} ${response.statusText}${
        text ? ` - ${text}` : ""
      }`,
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    return (await response.text()) as unknown as T;
  }

  return (await response.json()) as T;
}
