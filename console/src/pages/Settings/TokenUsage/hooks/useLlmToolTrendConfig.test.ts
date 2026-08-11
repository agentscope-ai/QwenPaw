import { describe, it, expect, vi } from "vitest";
import { renderHook } from "@testing-library/react";
import dayjs from "dayjs";
import { useLlmToolTrendConfig } from "./useLlmToolTrendConfig";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe("useLlmToolTrendConfig", () => {
  const startDate = dayjs("2026-04-24");
  const endDate = dayjs("2026-04-25");

  it("returns null when both LLM and tool series are empty", () => {
    const { result } = renderHook(() =>
      useLlmToolTrendConfig({
        byDate: null,
        dailyToolCalls: {},
        startDate,
        endDate,
        isDark: false,
      }),
    );
    expect(result.current).toBeNull();
  });

  it("builds a chart for tool-only data", () => {
    const { result } = renderHook(() =>
      useLlmToolTrendConfig({
        byDate: null,
        dailyToolCalls: { "2026-04-24": 2 },
        startDate,
        endDate,
        isDark: false,
      }),
    );
    expect(result.current).not.toBeNull();
    expect(result.current?.data.some((d) => d.value === 2)).toBe(true);
    expect(
      result.current?.data.every(
        (d) => d.category === "tokenUsage.toolCalls",
      ),
    ).toBe(true);
  });

  it("builds a chart for LLM-only data", () => {
    const { result } = renderHook(() =>
      useLlmToolTrendConfig({
        byDate: {
          "2026-04-24": {
            prompt_tokens: 1,
            completion_tokens: 1,
            call_count: 3,
          },
        },
        dailyToolCalls: {},
        startDate,
        endDate,
        isDark: true,
      }),
    );
    expect(result.current).not.toBeNull();
    expect(result.current?.data.some((d) => d.value === 3)).toBe(true);
    expect(
      result.current?.data.every(
        (d) => d.category === "tokenUsage.llmCalls",
      ),
    ).toBe(true);
  });

  it("omits tool series when toolCallsUnavailable is true", () => {
    const { result } = renderHook(() =>
      useLlmToolTrendConfig({
        byDate: {
          "2026-04-24": {
            prompt_tokens: 1,
            completion_tokens: 1,
            call_count: 3,
          },
        },
        dailyToolCalls: { "2026-04-24": 9 },
        startDate,
        endDate,
        isDark: false,
        toolCallsUnavailable: true,
      }),
    );
    expect(result.current).not.toBeNull();
    expect(
      result.current?.data.every(
        (d) => d.category === "tokenUsage.llmCalls",
      ),
    ).toBe(true);
    expect(result.current?.data.some((d) => d.value === 9)).toBe(false);
  });
});
