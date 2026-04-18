import { lazy } from "react";
import type { ComponentType } from "react";

const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

/**
 * A wrapper around `React.lazy` that retries the dynamic import on failure.
 *
 * Chunk loads can fail due to stale caches, transient network errors, or
 * deploy races.  After the initial attempt fails, this helper retries up to
 * {@link MAX_RETRIES} additional times (so up to 4 total attempts) with a
 * {@link RETRY_DELAY_MS} ms delay between each retry before giving up and
 * letting the error propagate to the nearest error boundary.
 */
export function lazyWithRetry<T extends ComponentType<unknown>>(
  factory: () => Promise<{ default: T }>,
) {
  return lazy(() => retryImport(factory, MAX_RETRIES));
}

function retryImport<T extends ComponentType<unknown>>(
  factory: () => Promise<{ default: T }>,
  retries: number,
): Promise<{ default: T }> {
  return factory().catch((error: unknown) => {
    if (retries <= 0) throw error;
    return new Promise<{ default: T }>((resolve) =>
      setTimeout(
        () => resolve(retryImport(factory, retries - 1)),
        RETRY_DELAY_MS,
      ),
    );
  });
}
