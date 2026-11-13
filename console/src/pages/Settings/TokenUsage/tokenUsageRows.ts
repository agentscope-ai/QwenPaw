/**
 * Row builders for the Token Usage tables.
 *
 * Extracted from TokenUsage/index.tsx so the row contract can be unit-tested
 * without rendering the page. Behaviour is unchanged.
 *
 * Regressions guarded here:
 * - #3368: the by-date table must list the newest date first. Users had to
 *   scroll to the bottom to find the latest day, so rows are sorted by date
 *   descending.
 */

export interface DateTokenRow {
  key: string;
  date: string;
  prompt_tokens: number;
  completion_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_eligible_input_tokens: number;
  cache_observed_calls: number;
  call_count: number;
}

export interface DateTokenStats {
  prompt_tokens: number;
  completion_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_eligible_input_tokens: number;
  cache_observed_calls: number;
  call_count: number;
}

/**
 * Builds by-date table rows sorted by date **descending** (newest first).
 * Regression guard for #3368.
 */
export function buildByDateRows(
  byDate: Record<string, DateTokenStats> | null | undefined,
): DateTokenRow[] {
  if (!byDate) return [];
  return Object.entries(byDate)
    .map(([date, stats]) => ({
      key: date,
      date,
      prompt_tokens: stats.prompt_tokens,
      completion_tokens: stats.completion_tokens,
      cache_read_tokens: stats.cache_read_tokens,
      cache_write_tokens: stats.cache_write_tokens,
      cache_eligible_input_tokens: stats.cache_eligible_input_tokens,
      cache_observed_calls: stats.cache_observed_calls,
      call_count: stats.call_count,
    }))
    .sort((a, b) => b.date.localeCompare(a.date));
}
