import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import {
  DEFAULT_LOOP_MODE,
  type LoopModeInfo,
  useLoopStore,
} from "../../stores/loopStore";
import { LoopModeSelector } from "./LoopModeSelector";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "zh" },
  }),
}));

const goal: LoopModeInfo = {
  id: "goal",
  name: "goal",
  slash_command: "goal",
  description: "Backend goal description",
  source: "builtin",
};
const custom: LoopModeInfo = {
  id: "custom:quality",
  name: "Quality Review",
  slash_command: "quality",
  description: "Keep the user's original description.",
  source: "custom",
};
const ompUltraqa: LoopModeInfo = {
  id: "plugin:ultraqa",
  name: "ultraqa",
  slash_command: "ultraqa",
  description:
    "**UltraQA** — automated QA cycle engine\n\n" +
    "Usage:\n" +
    '  `/ultraqa [--tests|--build|--lint|--typecheck|--custom "cmd"]`\n',
  name_i18n: {
    en: "UltraQA",
    "zh-CN": "UltraQA",
  },
  description_i18n: {
    en: "**UltraQA** — automated QA cycle engine",
    "zh-CN": "**UltraQA** — 自动化 QA 循环引擎",
  },
  source: "plugin",
};

describe("LoopModeSelector", () => {
  beforeEach(() => {
    useLoopStore.setState({
      selectedModeId: "default",
      availableModes: [DEFAULT_LOOP_MODE, goal, custom, ompUltraqa],
      sessionState: "idle",
      activeMode: null,
      catalogLoading: false,
      catalogError: false,
    });
  });

  it("shows localized built-ins and verbatim custom modes", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoopModeSelector />);

    await user.click(screen.getByRole("button", { name: "loop.selectorAria" }));

    expect(
      screen.getAllByText("loop.modes.default.name").length,
    ).toBeGreaterThan(0);
    expect(screen.getByText("loop.modes.goal.description")).toBeInTheDocument();
    expect(screen.getByText("Quality Review")).toBeInTheDocument();
    expect(
      screen.getByText("Keep the user's original description."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Backend goal description"),
    ).not.toBeInTheDocument();
    const ultraqaLabels = screen.getAllByText("UltraQA");
    expect(ultraqaLabels.length).toBeGreaterThanOrEqual(2);
    expect(ultraqaLabels.some((node) => node.tagName === "STRONG")).toBe(true);
    expect(screen.getByText(/自动化 QA 循环引擎/)).toBeInTheDocument();
    expect(
      screen.queryByText(/automated QA cycle engine/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/\*\*UltraQA\*\*/)).not.toBeInTheDocument();
    expect(screen.queryByText(/`\/ultraqa/)).not.toBeInTheDocument();
  });

  it("selects a custom mode from the compact menu", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LoopModeSelector />);

    await user.click(screen.getByRole("button", { name: "loop.selectorAria" }));
    await user.click(screen.getByText("Quality Review"));

    expect(useLoopStore.getState().selectedModeId).toBe("custom:quality");
  });

  it("shows starting before the first response event", () => {
    useLoopStore.getState().setStartingMode(custom);

    renderWithProviders(<LoopModeSelector />);

    expect(screen.getByText("Quality Review")).toBeInTheDocument();
    expect(screen.getByText("loop.starting")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "loop.selectorAria" }),
    ).not.toBeInTheDocument();
  });

  it("shows running after the first response event", () => {
    useLoopStore.getState().setSessionMode(custom, "running");

    renderWithProviders(<LoopModeSelector />);

    expect(screen.getByText("loop.running")).toBeInTheDocument();
  });

  it("shows that an active mode is waiting for the user", () => {
    useLoopStore.getState().setSessionMode(custom, "awaiting_user");

    renderWithProviders(<LoopModeSelector />);

    expect(screen.getByText("loop.awaiting_user")).toBeInTheDocument();
  });

  // ---------------------------------------------------------------------------
  // A#85096690 — session events trigger the indicator update
  // ---------------------------------------------------------------------------
  describe("session event triggers indicator refresh (#85096690)", () => {
    it("transitions from idle → starting → running and updates the indicator", () => {
      const { rerender } = renderWithProviders(<LoopModeSelector />);

      // Initially idle: selector trigger is visible
      expect(
        screen.getByRole("button", { name: "loop.selectorAria" }),
      ).toBeInTheDocument();

      // Session event: mode starting
      act(() => {
        useLoopStore.getState().setStartingMode(custom);
      });
      rerender(<LoopModeSelector />);
      expect(screen.getByText("loop.starting")).toBeInTheDocument();
      expect(screen.getByText("Quality Review")).toBeInTheDocument();

      // Session event: mode running
      act(() => {
        useLoopStore.getState().setRunningMode();
      });
      rerender(<LoopModeSelector />);
      expect(screen.getByText("loop.running")).toBeInTheDocument();
      expect(screen.getByText("Quality Review")).toBeInTheDocument();
    });

    it("resetSessionMode returns indicator to idle selector", () => {
      // Start in running state
      useLoopStore.getState().setSessionMode(custom, "running");
      const { rerender } = renderWithProviders(<LoopModeSelector />);
      expect(screen.getByText("loop.running")).toBeInTheDocument();

      // Session ends → reset
      act(() => {
        useLoopStore.getState().resetSessionMode();
      });
      rerender(<LoopModeSelector />);

      // Back to idle: selector trigger visible again, no session state text
      expect(
        screen.getByRole("button", { name: "loop.selectorAria" }),
      ).toBeInTheDocument();
      expect(screen.queryByText("loop.running")).not.toBeInTheDocument();
      expect(screen.queryByText("Quality Review")).not.toBeInTheDocument();
    });

    it("transitions running → awaiting_user → running correctly", () => {
      useLoopStore.getState().setSessionMode(custom, "running");
      const { rerender } = renderWithProviders(<LoopModeSelector />);
      expect(screen.getByText("loop.running")).toBeInTheDocument();

      // Switch to awaiting_user
      act(() => {
        useLoopStore.getState().setSessionMode(custom, "awaiting_user");
      });
      rerender(<LoopModeSelector />);
      expect(screen.getByText("loop.awaiting_user")).toBeInTheDocument();

      // Back to running
      act(() => {
        useLoopStore.getState().setSessionMode(custom, "running");
      });
      rerender(<LoopModeSelector />);
      expect(screen.getByText("loop.running")).toBeInTheDocument();
    });

    it("active mode indicator shows data-state attribute matching session state", () => {
      useLoopStore.getState().setSessionMode(goal, "running");
      renderWithProviders(<LoopModeSelector />);

      const indicator = screen
        .getByText("loop.running")
        .closest("[data-state]");
      expect(indicator).toBeTruthy();
      expect(indicator!.getAttribute("data-state")).toBe("running");
    });
  });
});
