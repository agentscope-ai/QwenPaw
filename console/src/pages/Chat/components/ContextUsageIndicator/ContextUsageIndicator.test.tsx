import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { useTurnUsageStore } from "../../turnUsageStore";
import ContextUsageIndicator from "./ContextUsageIndicator";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown>) => {
      const labels: Record<string, string> = {
        "chat.turnUsagePopover.contextLabel": "上下文窗口",
        "chat.turnUsagePopover.outerRing": "外圈",
        "chat.turnUsagePopover.cacheLabel": "缓存命中率",
        "chat.turnUsagePopover.centerValue": "中心",
        "chat.turnUsagePopover.cacheTokens": `命中 ${options?.readTok} / 输入 ${options?.inputTok}`,
        "chat.turnUsagePopover.manageContext": "上下文管理",
        "chat.turnUsagePopover.compact": "压缩",
        "chat.turnUsagePopover.new": "新对话",
      };
      if (key === "chat.turnUsagePopover.ariaLabel") {
        return `上下文占用 ${options?.contextRate}，缓存命中 ${options?.cacheRate}`;
      }
      return labels[key] ?? key;
    },
  }),
}));

vi.mock("antd", async (importOriginal) => {
  const actual = await importOriginal<typeof import("antd")>();
  return {
    ...actual,
    Popover: ({
      children,
      content,
    }: {
      children: ReactNode;
      content: ReactNode;
    }) => (
      <>
        {children}
        <div>{content}</div>
      </>
    ),
  };
});

afterEach(() => {
  useTurnUsageStore.getState().invalidateTurn();
});

function setUsage(cacheRate: number) {
  useTurnUsageStore.getState().setSnapshot({
    usage: {
      session_cache_read_tokens: cacheRate,
      session_cache_eligible_input_tokens: 100,
      session_cache_observed: true,
      session_cache_hit_rate: cacheRate,
    },
    context_usage: {
      estimated_tokens: 24000,
      max_input_length: 100000,
      context_usage_ratio: 24,
    },
  });
}

describe("ContextUsageIndicator", () => {
  it("renders a compact fusion dial with explicit shared details", () => {
    setUsage(94);

    const view = renderWithProviders(
      <ContextUsageIndicator onCompact={vi.fn()} onNew={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", {
        name: "上下文占用 24%，缓存命中 94%",
      }),
    ).toHaveTextContent("94");
    expect(view.container.querySelector("svg")?.getAttribute("width")).toBe(
      "24",
    );
    expect(screen.getByText("上下文窗口")).toBeInTheDocument();
    expect(screen.getByText("缓存命中率")).toBeInTheDocument();
    expect(screen.getByText("外圈 · 24K / 100K")).toBeInTheDocument();
    expect(screen.getByText("中心 · 命中 94 / 输入 100")).toBeInTheDocument();
  });

  it("keeps the cold-start cache value visible as zero", () => {
    setUsage(0);

    renderWithProviders(
      <ContextUsageIndicator onCompact={vi.fn()} onNew={vi.fn()} />,
    );

    expect(
      screen.getByRole("button", {
        name: "上下文占用 24%，缓存命中 0%",
      }),
    ).toHaveTextContent("0");
  });
});
