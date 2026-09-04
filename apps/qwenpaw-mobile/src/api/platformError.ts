export class PlatformRequestError extends Error {
  readonly status: number;
  readonly retryAfterMs: number | null;
  readonly code?: string;

  constructor(
    message: string,
    options: {
      status: number;
      retryAfterMs?: number | null;
      code?: string;
    },
  ) {
    super(message);
    this.name = "PlatformRequestError";
    this.status = options.status;
    this.retryAfterMs = options.retryAfterMs ?? null;
    this.code = options.code;
  }
}

export function parseRetryAfter(
  value: string | null,
  now = Date.now(),
): number | null {
  if (!value) return null;
  const seconds = Number(value);
  if (Number.isFinite(seconds) && seconds >= 0) return seconds * 1000;
  const date = Date.parse(value);
  if (!Number.isFinite(date)) return null;
  return Math.max(0, date - now);
}

export function isPlatformRateLimitError(
  error: unknown,
): error is PlatformRequestError {
  return error instanceof PlatformRequestError && error.status === 429;
}

export function platformRateLimitDelay(
  error: unknown,
  failureCount: number,
): number | null {
  if (!isPlatformRateLimitError(error)) return null;
  const exponential = Math.min(
    60_000,
    20_000 * (2 ** Math.max(0, failureCount)),
  );
  return Math.max(exponential, error.retryAfterMs ?? 0);
}

export function isInvalidPlatformSessionError(error: unknown): boolean {
  if (!(error instanceof PlatformRequestError)) return false;
  if (error.status === 401) return true;
  return [
    "ASP.AUTH.SESSION_INVALID",
    "SESSION_INVALID",
    "UNAUTHORIZED",
    "UNAUTHENTICATED",
  ].includes(error.code ?? "");
}
