import { screen } from "@testing-library/react";
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
  useTranslation: () => ({ t: (key: string) => key }),
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

describe("LoopModeSelector", () => {
  beforeEach(() => {
    useLoopStore.setState({
      selectedModeId: "default",
      availableModes: [DEFAULT_LOOP_MODE, goal, custom],
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
});
