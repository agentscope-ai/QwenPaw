import assert from "node:assert/strict";
import test from "node:test";

import {
  isInvalidPlatformSessionError,
  isPlatformRateLimitError,
  parseRetryAfter,
  PlatformRequestError,
  platformRateLimitDelay,
} from "./platformError";

test("parses Retry-After seconds and dates", () => {
  assert.equal(parseRetryAfter("12"), 12_000);
  assert.equal(
    parseRetryAfter("Thu, 01 Jan 2026 00:01:00 GMT", Date.UTC(2026, 0, 1)),
    60_000,
  );
  assert.equal(parseRetryAfter("invalid"), null);
});

test("applies bounded exponential backoff to Platform 429 responses", () => {
  const error = new PlatformRequestError("Too many requests", {
    status: 429,
    retryAfterMs: 25_000,
  });
  assert.equal(isPlatformRateLimitError(error), true);
  assert.equal(platformRateLimitDelay(error, 0), 25_000);
  assert.equal(platformRateLimitDelay(error, 1), 40_000);
  assert.equal(platformRateLimitDelay(error, 5), 60_000);
});

test("only authentication responses invalidate a Platform session", () => {
  assert.equal(isInvalidPlatformSessionError(
    new PlatformRequestError("Unauthorized", { status: 401 }),
  ), true);
  assert.equal(isInvalidPlatformSessionError(
    new PlatformRequestError("Limited", { status: 429 }),
  ), false);
  assert.equal(isInvalidPlatformSessionError(
    new PlatformRequestError("Forbidden", { status: 403 }),
  ), false);
  assert.equal(isInvalidPlatformSessionError(
    new PlatformRequestError("Expired", {
      code: "ASP.AUTH.SESSION_INVALID",
      status: 403,
    }),
  ), true);
});
